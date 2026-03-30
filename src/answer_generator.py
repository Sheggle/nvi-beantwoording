"""Async OpenAI-based answer generator with rate limiting."""

import asyncio
import json
import time
from typing import AsyncIterator, Callable

from openai import AsyncOpenAI

from .models import (
    GeneratedAnswer,
    LLMResponse,
    NvIQuestion,
    Trajectory,
    VerificationResponse,
)
from .config import Settings
from .section_matcher import SectionMatcher, MatchResult
from .supplementary_matcher import SupplementaryMatcher
from .background_context import BACKGROUND_CONTEXT
from .few_shot_examples import FEW_SHOT_EXAMPLES


class TokenBucket:
    """Simple token bucket for rate limiting."""

    def __init__(self, rate: float, capacity: float):
        self.rate = rate  # tokens per second
        self.capacity = capacity
        self.tokens = capacity
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        """Acquire tokens, waiting if necessary."""
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self.last_update
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                self.last_update = now

                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return

                # Wait for tokens to accumulate
                wait_time = (tokens - self.tokens) / self.rate
                await asyncio.sleep(wait_time)


class AnswerGenerator:
    """Generates answers using async OpenAI API calls with structured outputs."""

    BASE_SYSTEM_PROMPT = """Je bent een expert op het gebied van het zorginkoopbeleid van Zilveren Kruis voor de Wet langdurige zorg (Wlz).

Je taak is om vragen uit de Nota van Inlichtingen te beantwoorden namens Zilveren Kruis (het zorgkantoor). Gebruik de verstrekte achtergrondkennis en beleidstekst.

Richtlijnen:
- Antwoord in 1-4 zinnen. Wees direct en stellig, vermijd hedging en overmatige uitleg.
- Gebruik "Zilveren Kruis" als je het over het zorgkantoor hebt, niet alleen "het zorgkantoor".
- Als een vraag buiten het bereik van het zorgkantoor valt (bijv. NZa-tarieven, tariefstructuur), verwijs door naar de juiste instantie in plaats van te speculeren.
- Gebruik de achtergrondkennis om vragen correct te kaderen binnen de rolverdeling NZa/zorgkantoor/VWS.
- Bij ja/nee-vragen: begin met een duidelijk "Ja" of "Nee", gevolgd door de onderbouwing. Niet hedgen.
- Wees accuraat en verwijs naar specifieke secties waar relevant.
- Schrijf in het Nederlands.

BELANGRIJK — Lees de beleidstekst EN achtergrondkennis zorgvuldig:
- Lees de VOLLEDIGE verstrekte beleidstekst EN achtergrondkennis voordat je concludeert dat informatie ontbreekt.
- De achtergrondkennis bevat procedurele informatie en jargon die niet altijd in de beleidstekst staat — gebruik deze als bron.
- Als het antwoord af te leiden IS uit de tekst of achtergrondkennis, beantwoord de vraag dan — zeg NIET dat de informatie niet beschikbaar is.
- Gebruik specifieke details: noem secties, percentages, termijnen, normen, jaartallen.
- Als de vraag verwijst naar een specifieke paragraaf, citeer relevante details UIT die paragraaf.
- "Unanswerable" is alleen correct als de informatie echt niet in de tekst EN niet in de achtergrondkennis staat.

Voorbeelden van het gewenste antwoordniveau:

Vraag: Wanneer er twee contracten worden aangevraagd, moeten er dan ook twee x 3 nieuwe succesvolle innovatieve initiatieven geïmplementeerd worden?
Antwoord: Nee. We verwachten dat u voor uw organisatie als geheel 3 nieuwe succesvolle initiatieven implementeert.

Vraag: Hoe gaan zorgaanbieders de noodzakelijke investeringen en kosten voor verduurzaming vergoed krijgen?
Antwoord: Het zorgkantoor gaat niet over de maximum tarieven van de NZa. Eventuele vragen daarover verzoeken wij u te stellen aan de NZa. Zilveren Kruis vergoedt 100% van de NHC/NIC-component. Meer kan en mag niet.

Vraag: Betekent het werken met integrale tarieven dat de componenten loon, materieel, NHC en NIC onderling uitwisselbaar zijn?
Antwoord: De NZa stelt de tarieven vast. Zij geeft aan dat de Wlz volledig integrale tarieven kent: één tarief waarvan alles bekostigd moet worden.
"""

    _MAATWERK_BLOCK = """

Maatwerk-antwoorden:
Sommige vragen gaan over situaties die per zorgaanbieder verschillen en niet generiek beantwoord kunnen worden. In die gevallen is het correct om te verwijzen naar individueel overleg. Voorbeelden:

Vraag: Welk tarief krijgen wij voor onze nieuwe locatie met hogere bouwkosten?
Antwoord: Dit is maatwerk. Neem hierover contact op met uw zorginkoper voor een individuele beoordeling.

Vraag: Kunnen wij afwijken van de standaard personeelsnorm gezien onze specifieke doelgroep?
Antwoord: Dit betreft een maatwerkafspraak. Wij adviseren u dit te bespreken met uw zorginkoper.

Vraag: Hoe wordt omgegaan met de extra kosten voor ons specifieke gebouw?
Antwoord: Dit is afhankelijk van uw individuele situatie. Neem contact op met uw zorginkoper om de mogelijkheden te bespreken."""

    _QUOTE_BEFORE_CONCLUDE_BLOCK = """

Citeer-dan-concludeer:
Wanneer een ja/nee-antwoord wordt verwacht, citeer eerst de relevante passage uit de beleidstekst en geef dan je conclusie. Voorbeeld:
Vraag: Geldt de korting ook voor nieuwe aanbieders?
Antwoord: In de beleidstekst staat: "[relevante passage]". Op basis hiervan: ja/nee, [conclusie]."""

    # --- Iteration 14 blocks (ablation-ready) ---

    _NZA_ROLE_EMPHASIS_BLOCK = """

Vraag: De tariefafslag op bepaalde zorgprofielen is onduidelijk. Hoe is deze tot stand gekomen?
Antwoord: De NZa is verantwoordelijk voor het vaststellen van de maximumtarieven per prestatie. De door Zilveren Kruis geboden tariefpercentages zijn bepaald volgens de methodiek in bijlage 7, waarbij is getoetst of minimaal 75% van de aanbieders een positief resultaat behaalt (sectie 2.3.2).

Vraag: Het breder kijken naar passende zorg vergt meer tijd en kennis. Hoe wordt dit financieel gedekt?
Antwoord: VPT en intramurale zorg kennen integrale tarieven waarin alle kosten zijn opgenomen. De NZa beleidsregel en prestatiebeschrijvingen beschrijven welke activiteiten binnen een prestatie vallen. Zorgkantoren volgen de NZa wet- en regelgeving voor financiering. Efficiëntere zorgverlening door zelfredzaamheid kan binnen het integrale tarief worden gerealiseerd.

Vraag: De inzet van technologie is gelimiteerd in uren per maand. Kan dit worden aangepast?
Antwoord: De NZa stelt de prestatiecodes op en bepaalt de inhoud en omvang daarvan. Zilveren Kruis kan de prestatiecodes niet eenzijdig wijzigen. Onze ervaring in de praktijk is dat de vastgestelde uren toereikend zijn.

Vraag: Zijn de tarieven hoog genoeg voor een gezonde bedrijfsvoering?
Antwoord: De tariefsystematiek beoogt een reëel tarief te bieden voor een redelijk efficiënt functionerende zorgaanbieder. Mocht de systematiek leiden tot een onverwacht benadelend effect, dan is de hardheidsclausule bedoeld als remedie. Doelmatig werken is daarvoor een voorwaarde. De procedure staat beschreven in hoofdstuk 7 / sectie 7.9.5."""

    _VV_FEW_SHOT_BLOCK = """

Vraag: Moeten alle zorgaanbieders alle vier essentiële voorzieningen bieden?
Antwoord: Nee. Welke essentiële voorzieningen een zorgaanbieder levert, hangt af van de situatie in de regio. Het is een gezamenlijke verantwoordelijkheid van zorgaanbieders, die dit onderling afspreken in afstemming met het zorgkantoor.

Vraag: Wat is doorslaggevend bij het maken van regionale afspraken over zorgverdeling?
Antwoord: Het maken van afspraken over wie welke zorg levert is een gezamenlijk proces van zorgkantoor en zorgaanbieders, waarbij Zilveren Kruis een sturende rol heeft. De afspraken sluiten aan bij landelijke programma's (IZA, WOZO, GALA) en zijn gericht op efficiënte en doelmatige zorgverlening.

Vraag: Hoe worden integrale tarieven bij VPT en intramurale zorg verantwoord?
Antwoord: VPT en intramurale zorg kennen integrale tarieven, waarin alle kosten zijn opgenomen. De NZa beleidsregel en prestatiebeschrijvingen beschrijven wat binnen een prestatie valt. Efficiëntere zorgverlening door zelfredzaamheid kan binnen het integrale tarief worden gerealiseerd.

Vraag: Zijn er nog strategische partnerschappen in het inkoopbeleid 2024-2026?
Antwoord: Bestaande strategische partnerschappen blijven geldig voor de afgesproken looptijd. Sectie 6.18 beschrijft de mogelijkheden voor afspraken op maat en samenwerking met innovatieve zorgaanbieders. Het inkoopbeleid biedt dus wel degelijk ruimte voor strategische samenwerking.

Vraag: Is het richttariefpercentage 95,5% gegarandeerd voor de hele beleidsperiode?
Antwoord: Het richttariefpercentage van 95,5% geldt voor reguliere bestaande aanbieders voor 2024-2026. Er zijn uitzonderingen (secties 2.4.2, 2.4.3, 2.4.4). Daarnaast kan 100% zekerheid niet worden gegeven vanwege mogelijke beleidswijzigingen of gewijzigde wet- en regelgeving.

Vraag: Hoe kan een zorgaanbieder bezwaar maken als het tarief niet kostendekkend is?
Antwoord: De hardheidsclausule is bedoeld als remedie voor onverwacht benadelend effect van de tariefsystematiek. Doelmatig werken is een voorwaarde. De procedure en deadlines staan beschreven in hoofdstuk 7 / sectie 7.9.5. Het tarief moet een reëel tarief zijn voor efficiënte zorglevering.

Vraag: Hoe wordt bij VPT omgegaan met NHC en duurzaamheid?
Antwoord: Bij VPT in een ongeclusterde setting is de huisvestingscomponent (NHC) niet van toepassing — er geldt geen NHC-verantwoording. Bij geclusterd VPT verwacht Zilveren Kruis wel een dialoog met eigenaren van vastgoed over verduurzaming. Pas geen intramurale verantwoordingseisen toe op ongeclusterd VPT.

Vraag: Worden afspraken over regionaal inkoopbeleid eenzijdig bepaald?
Antwoord: Nee. Het beleidskader is landelijk hetzelfde, maar de invulling en uitwerking verschilt per zorgkantoorregio. Afspraken worden gemaakt in overleg met zorgaanbieders — het proces is gebaseerd op redelijkheid en billijkheid."""

    _SECTION_CITATIONS_BLOCK = """

SECTIEREFERENTIES — verwijs altijd naar specifieke secties:
- Als je informatie uit een specifieke sectie, bijlage of hoofdstuk haalt, noem het nummer (bijv. "zie sectie 2.4.2", "bijlage 6", "hoofdstuk 7").
- Bij uitzonderingen of aanvullende regels: verwijs naar de sectie waar deze staan.
- Bij termen die in bijlagen gedefinieerd zijn: noem de bijlage."""

    _COLLABORATIVE_FRAMING_BLOCK = """

GEZAMENLIJK PROCES — kader besluitvorming correct:
- Regionale afspraken, essentiële voorzieningen en zorgverdeling zijn een gezamenlijke verantwoordelijkheid van zorgkantoor én zorgaanbieders.
- Gebruik formuleringen als "in overleg met", "gezamenlijk", "in afstemming met" waar van toepassing.
- Vermijd de suggestie dat Zilveren Kruis eenzijdig beslist over zaken die in de praktijk in samenwerking worden bepaald.
- Processen als inkoopbeleid herijking, spiegelinformatie-duiding en regionale invulling zijn altijd in samenspraak met de sector."""

    _CALIBRATED_CONFIDENCE_BLOCK = """

Betrouwbaarheidsniveaus (wees streng en eerlijk):
- high: Het antwoord staat letterlijk of vrijwel letterlijk in de tekst. Geen interpretatie nodig.
- medium: Relevante informatie is aanwezig maar vereist interpretatie of het combineren van passages. Of: het antwoord volgt logisch uit de achtergrondkennis maar staat niet expliciet in de beleidstekst.
- low: Het onderwerp wordt slechts zijdelings benoemd. Het antwoord is grotendeels een beredeneerde inschatting.
- unanswerable: De informatie staat niet in de tekst, betreft een intern proces, of valt buiten scope."""

    _DEFAULT_CONFIDENCE_BLOCK = """

Betrouwbaarheidsniveaus:
- high: De kernvraag kan worden beantwoord met de tekst en/of achtergrondkennis
- medium: Relevante informatie beschikbaar, maar belangrijke onderdelen ontbreken
- low: Alleen zijdelings gerelateerde informatie beschikbaar
- unanswerable: Geen relevante informatie in de tekst of achtergrondkennis"""

    VERIFY_SYSTEM_PROMPT = """Je bent een feitencontroleur voor antwoorden over het zorginkoopbeleid van Zilveren Kruis (Wlz).

Je krijgt een concept-antwoord en de broncontext waarop het gebaseerd zou moeten zijn. Je taak:
1. Identificeer alle feitelijke claims in het antwoord.
2. Controleer elke claim tegen de verstrekte context (beleidstekst + achtergrondkennis).
3. Als er claims zijn die NIET ondersteund worden door de context, herschrijf dan het antwoord zodat alleen onderbouwde claims overblijven. Vervang ononderbouwde claims door voorzichtigere formuleringen of laat ze weg.
4. Als alle claims ondersteund zijn, geef het originele antwoord terug als revised_answer.

Wees streng: als een specifiek getal, percentage of beleidsdetail niet in de context staat, markeer het als niet-ondersteund."""

    RETRIEVAL_SYSTEM_PROMPT = """Je bent een expert op het gebied van het zorginkoopbeleid van Zilveren Kruis voor de Wet langdurige zorg (Wlz).

Je taak is om vragen uit de Nota van Inlichtingen te beantwoorden. Je hebt twee zoektools tot je beschikking om relevante informatie op te zoeken. Gebruik deze tools om de juiste beleidstekst en aanvullende bronnen te vinden voordat je antwoord geeft.

Achtergrondkennis:
{background}

Richtlijnen:
- Zoek eerst naar relevante informatie voordat je antwoordt.
- Je mag meerdere zoekopdrachten doen als dat nodig is.
- Antwoord in 1-4 zinnen. Wees direct en stellig.
- Als een vraag buiten het bereik van het zorgkantoor valt, verwijs door.
- Als je onvoldoende informatie vindt, geef dat eerlijk aan.
- Schrijf in het Nederlands."""

    RETRIEVAL_TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "search_beleidstekst",
                "description": "Zoek in het inkoopbeleid document. Geeft relevante secties terug op basis van een zoekvraag en optioneel een sectienummer.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Zoekvraag, bijv. 'richttariefpercentage' of 'innovatie kwaliteitskader'",
                        },
                        "section_nr": {
                            "type": "string",
                            "description": "Optioneel sectienummer om in te zoeken, bijv. '3.2'",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_aanvullende_bronnen",
                "description": "Zoek in aanvullende referentiedocumenten (NZa-beleidsregels, Zilveren Kruis bijlagen, etc.).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Zoekvraag voor aanvullende bronnen",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
    ]

    MAX_RETRIEVAL_ITERATIONS = 5

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.client = AsyncOpenAI(api_key=self.settings.openai_api_key)
        self._semaphore = asyncio.Semaphore(self.settings.max_concurrent_requests)
        self._token_bucket = TokenBucket(
            rate=self.settings.requests_per_minute / 60.0,
            capacity=self.settings.max_concurrent_requests,
        )

    def _get_active_improvements(self) -> list[str]:
        """Return list of active improvement names."""
        active = []
        if self.settings.enable_maatwerk_examples:
            active.append("maatwerk_examples")
        if self.settings.enable_quote_before_conclude:
            active.append("quote_before_conclude")
        if self.settings.enable_verify_loop:
            active.append("verify_loop")
        if self.settings.enable_calibrated_confidence:
            active.append("calibrated_confidence")
        if self.settings.enable_model_guided_retrieval:
            active.append("model_guided_retrieval")
        if self.settings.enable_nza_role_emphasis:
            active.append("nza_role_emphasis")
        if self.settings.enable_vv_few_shot:
            active.append("vv_few_shot")
        if self.settings.enable_section_citations:
            active.append("section_citations")
        if self.settings.enable_collaborative_framing:
            active.append("collaborative_framing")
        return active

    def _build_system_prompt(self) -> str:
        """Build the system prompt, conditionally appending improvement blocks."""
        prompt = self.BASE_SYSTEM_PROMPT

        # Always-on few-shot examples
        prompt += FEW_SHOT_EXAMPLES

        if self.settings.enable_maatwerk_examples:
            prompt += self._MAATWERK_BLOCK

        if self.settings.enable_quote_before_conclude:
            prompt += self._QUOTE_BEFORE_CONCLUDE_BLOCK

        # Iteration 14 blocks
        if self.settings.enable_nza_role_emphasis:
            prompt += self._NZA_ROLE_EMPHASIS_BLOCK

        if self.settings.enable_vv_few_shot:
            prompt += self._VV_FEW_SHOT_BLOCK

        if self.settings.enable_section_citations:
            prompt += self._SECTION_CITATIONS_BLOCK

        if self.settings.enable_collaborative_framing:
            prompt += self._COLLABORATIVE_FRAMING_BLOCK

        if self.settings.enable_calibrated_confidence:
            prompt += self._CALIBRATED_CONFIDENCE_BLOCK
        else:
            prompt += self._DEFAULT_CONFIDENCE_BLOCK

        return prompt

    def _build_retrieval_system_prompt(self) -> str:
        """Build the system prompt for model-guided retrieval mode."""
        prompt = self.RETRIEVAL_SYSTEM_PROMPT.format(background=BACKGROUND_CONTEXT)

        if self.settings.enable_maatwerk_examples:
            prompt += self._MAATWERK_BLOCK

        if self.settings.enable_quote_before_conclude:
            prompt += self._QUOTE_BEFORE_CONCLUDE_BLOCK

        if self.settings.enable_calibrated_confidence:
            prompt += self._CALIBRATED_CONFIDENCE_BLOCK
        else:
            prompt += self._DEFAULT_CONFIDENCE_BLOCK

        return prompt

    def _build_user_prompt(
        self,
        question: NvIQuestion,
        context: str,
        match_result: MatchResult,
        supplementary_context: str = "",
    ) -> str:
        """Build the user prompt for the LLM."""
        section_info = f" (sectie {question.section})" if question.section else ""

        supp_section = ""
        if supplementary_context:
            supp_section = f"\n\nAANVULLENDE BRONNEN:\n{supplementary_context}"

        if not context:
            return f"""ACHTERGRONDKENNIS:
{BACKGROUND_CONTEXT}

BELEIDSTEKST:
Geen relevante secties gevonden in het inkoopbeleid.{supp_section}

VRAAG{section_info}:
{question.question}

Beantwoord op basis van de achtergrondkennis en eventuele aanvullende bronnen, of geef aan dat deze vraag niet beantwoord kan worden."""

        return f"""ACHTERGRONDKENNIS:
{BACKGROUND_CONTEXT}

BELEIDSTEKST:
{context}{supp_section}

VRAAG{section_info}:
{question.question}"""

    async def _verify_answer(
        self, draft_answer: str, user_prompt: str
    ) -> VerificationResponse | None:
        """Run a verification pass on a draft answer (Improvement 3).

        Returns VerificationResponse or None on failure.
        """
        verify_prompt = f"""{user_prompt}

CONCEPT-ANTWOORD:
{draft_answer}

Controleer dit concept-antwoord tegen de bovenstaande context."""

        await self._token_bucket.acquire()

        try:
            response = await self.client.beta.chat.completions.parse(
                model=self.settings.model,
                messages=[
                    {"role": "system", "content": self.VERIFY_SYSTEM_PROMPT},
                    {"role": "user", "content": verify_prompt},
                ],
                response_format=VerificationResponse,
                temperature=0.0,
                max_tokens=800,
            )
            return response.choices[0].message.parsed
        except Exception:
            return None

    def _execute_section_search(
        self, query: str, section_nr: str | None, matcher: SectionMatcher
    ) -> str:
        """Execute a search_beleidstekst tool call."""
        import re

        query_lower = query.lower()
        words = re.findall(r"\b[a-zA-Z]{4,}\b", query_lower)

        results = []

        # If section_nr provided, try direct match first
        if section_nr:
            from .models import NvIQuestion
            fake_q = NvIQuestion(section=section_nr, question=query, answer="")
            match = matcher.match(fake_q)
            if match.matched_sections:
                results = match.matched_sections

        # Keyword search as fallback or supplement
        if not results:
            section_scores: dict[str, int] = {}
            for word in words:
                if word in matcher._keyword_index:
                    for section in matcher._keyword_index[word]:
                        section_scores[section.section] = section_scores.get(section.section, 0) + 1

            if section_scores:
                sorted_sections = sorted(
                    section_scores.items(), key=lambda x: x[1], reverse=True
                )[:5]
                results = [matcher._section_index[s[0]] for s in sorted_sections]

        if not results:
            return "Geen relevante secties gevonden."

        return matcher.get_context_text(results)

    def _execute_supplementary_search(
        self, query: str, supplementary_matcher: SupplementaryMatcher | None
    ) -> str:
        """Execute a search_aanvullende_bronnen tool call."""
        if not supplementary_matcher:
            return "Geen aanvullende bronnen beschikbaar."

        from .models import NvIQuestion
        fake_q = NvIQuestion(section="", question=query, answer="")
        result = supplementary_matcher.match(fake_q)

        if not result.matched_chunks:
            return "Geen relevante aanvullende bronnen gevonden."

        return supplementary_matcher.get_context_text(result.matched_chunks)

    async def _generate_answer_with_retrieval(
        self,
        question: NvIQuestion,
        matcher: SectionMatcher,
        supplementary_matcher: SupplementaryMatcher | None,
        trajectory: Trajectory,
    ) -> GeneratedAnswer:
        """Improvement 5: Model-guided retrieval with tool calling loop."""
        system_prompt = self._build_retrieval_system_prompt()
        section_info = f" (sectie {question.section})" if question.section else ""
        user_content = f"VRAAG{section_info}:\n{question.question}"

        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        trajectory.full_prompt = user_content
        tool_calls_log: list[dict] = []

        for iteration in range(self.MAX_RETRIEVAL_ITERATIONS):
            await self._token_bucket.acquire()

            async with self._semaphore:
                response = await self.client.chat.completions.create(
                    model=self.settings.model,
                    messages=messages,
                    tools=self.RETRIEVAL_TOOLS,
                    temperature=0.1,
                    max_tokens=800,
                )

            msg = response.choices[0].message

            # If no tool calls, the model is done — extract final answer
            if not msg.tool_calls:
                # Append the assistant message and do a final structured parse
                messages.append({"role": "assistant", "content": msg.content or ""})
                break

            # Process tool calls
            messages.append(msg.model_dump(exclude_none=True))

            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments)
                tool_log = {
                    "iteration": iteration,
                    "tool": tc.function.name,
                    "arguments": args,
                }

                if tc.function.name == "search_beleidstekst":
                    result_text = self._execute_section_search(
                        args["query"], args.get("section_nr"), matcher
                    )
                elif tc.function.name == "search_aanvullende_bronnen":
                    result_text = self._execute_supplementary_search(
                        args["query"], supplementary_matcher
                    )
                else:
                    result_text = "Onbekende tool."

                tool_log["result_length"] = len(result_text)
                tool_calls_log.append(tool_log)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_text,
                })
        else:
            # Safety cap reached — add instruction to conclude
            messages.append({
                "role": "user",
                "content": "Je hebt het maximale aantal zoekstappen bereikt. Geef nu je antwoord op basis van de gevonden informatie.",
            })

        trajectory.retrieval_tool_calls = tool_calls_log

        # Final structured parse to get LLMResponse
        await self._token_bucket.acquire()

        async with self._semaphore:
            messages.append({
                "role": "user",
                "content": "Geef nu je definitieve antwoord in het gevraagde format.",
            })

            try:
                final_response = await self.client.beta.chat.completions.parse(
                    model=self.settings.model,
                    messages=messages,
                    response_format=LLMResponse,
                    temperature=0.1,
                    max_tokens=500,
                )

                raw_msg = final_response.choices[0].message
                trajectory.raw_response = {
                    "content": raw_msg.content,
                    "model": final_response.model,
                    "usage": {
                        "prompt_tokens": final_response.usage.prompt_tokens,
                        "completion_tokens": final_response.usage.completion_tokens,
                    } if final_response.usage else None,
                }

                llm_response = raw_msg.parsed
                if llm_response:
                    answer_text = llm_response.answer

                    # Apply verify loop if enabled
                    if self.settings.enable_verify_loop:
                        # Build a context summary from tool call results for verification
                        context_summary = "\n".join(
                            m["content"] for m in messages if m.get("role") == "tool"
                        )
                        verify_prompt = f"ACHTERGRONDKENNIS:\n{BACKGROUND_CONTEXT}\n\nBELEIDSTEKST:\n{context_summary}\n\nVRAAG:\n{question.question}"
                        verification = await self._verify_answer(answer_text, verify_prompt)
                        if verification:
                            trajectory.verification_response = verification.model_dump()
                            if verification.unsupported_claims:
                                answer_text = verification.revised_answer

                    return GeneratedAnswer(
                        section_nr=question.section,
                        question=question.question,
                        answer=answer_text,
                        confidence=llm_response.confidence,
                        source_sections=llm_response.source_sections,
                        reasoning=llm_response.reasoning,
                        original_answer=question.answer,
                        trajectory=trajectory,
                    )
                else:
                    raise ValueError("Empty response from LLM")

            except Exception as e:
                trajectory.raw_response = {"error": str(e)}
                return GeneratedAnswer(
                    section_nr=question.section,
                    question=question.question,
                    answer=f"Fout bij het genereren van antwoord: {str(e)}",
                    confidence="unanswerable",
                    source_sections=[],
                    reasoning=f"API error: {str(e)}",
                    original_answer=question.answer,
                    trajectory=trajectory,
                )

    async def generate_answer(
        self,
        question: NvIQuestion,
        matcher: SectionMatcher,
        supplementary_matcher: SupplementaryMatcher | None = None,
    ) -> GeneratedAnswer:
        """Generate an answer for a single question.

        Args:
            question: The NvI question to answer
            matcher: Section matcher with loaded Inkoopbeleid sections
            supplementary_matcher: Optional matcher for supplementary documents

        Returns:
            GeneratedAnswer with the response
        """
        # Match question to relevant sections
        match_result = matcher.match(question)

        # Build context from matched sections
        context = matcher.get_context_text(match_result.matched_sections)

        # Match supplementary documents
        supplementary_context = ""
        supp_chunks_info = []
        if supplementary_matcher:
            supp_result = supplementary_matcher.match(question)
            if supp_result.matched_chunks:
                supplementary_context = supplementary_matcher.get_context_text(
                    supp_result.matched_chunks
                )
                supp_chunks_info = [
                    {"doc_id": c.doc_id, "section": c.section, "title": c.title}
                    for c in supp_result.matched_chunks
                ]

        # Build trajectory
        trajectory = Trajectory(
            match_type=match_result.match_type,
            match_details=match_result.match_details,
            matched_inkoopbeleid_sections=[s.section for s in match_result.matched_sections],
            matched_supplementary_chunks=supp_chunks_info,
            active_improvements=self._get_active_improvements(),
        )

        # Handle case where no sections matched (skip for model-guided retrieval)
        if not self.settings.enable_model_guided_retrieval:
            if not match_result.matched_sections and not supplementary_context:
                trajectory.full_prompt = None
                trajectory.raw_response = None
                return GeneratedAnswer(
                    section_nr=question.section,
                    question=question.question,
                    answer="Deze vraag kan niet worden beantwoord op basis van het beschikbare inkoopbeleid. Er zijn geen relevante secties gevonden.",
                    confidence="unanswerable",
                    source_sections=[],
                    reasoning=f"Geen match gevonden: {match_result.match_details}",
                    original_answer=question.answer,
                    trajectory=trajectory,
                )

        # Improvement 5: Model-guided retrieval (replaces normal flow)
        if self.settings.enable_model_guided_retrieval:
            return await self._generate_answer_with_retrieval(
                question, matcher, supplementary_matcher, trajectory
            )

        # Normal flow: build prompt and call LLM
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(
            question, context, match_result, supplementary_context
        )
        trajectory.full_prompt = user_prompt

        # Rate limiting
        await self._token_bucket.acquire()

        async with self._semaphore:
            try:
                # Use structured outputs with Pydantic model
                response = await self.client.beta.chat.completions.parse(
                    model=self.settings.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format=LLMResponse,
                    temperature=0.1,
                    max_tokens=500,
                )

                # Capture raw response
                raw_msg = response.choices[0].message
                trajectory.raw_response = {
                    "content": raw_msg.content,
                    "model": response.model,
                    "usage": {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                    } if response.usage else None,
                }

                # Response is already parsed into LLMResponse
                llm_response = raw_msg.parsed
                if llm_response:
                    answer_text = llm_response.answer

                    # Improvement 3: Verify loop
                    if self.settings.enable_verify_loop:
                        verification = await self._verify_answer(
                            answer_text, user_prompt
                        )
                        if verification:
                            trajectory.verification_response = verification.model_dump()
                            if verification.unsupported_claims:
                                answer_text = verification.revised_answer

                    return GeneratedAnswer(
                        section_nr=question.section,
                        question=question.question,
                        answer=answer_text,
                        confidence=llm_response.confidence,
                        source_sections=llm_response.source_sections,
                        reasoning=llm_response.reasoning,
                        original_answer=question.answer,
                        trajectory=trajectory,
                    )
                else:
                    raise ValueError("Empty response from LLM")

            except Exception as e:
                trajectory.raw_response = {"error": str(e)}
                return GeneratedAnswer(
                    section_nr=question.section,
                    question=question.question,
                    answer=f"Fout bij het genereren van antwoord: {str(e)}",
                    confidence="unanswerable",
                    source_sections=[],
                    reasoning=f"API error: {str(e)}",
                    original_answer=question.answer,
                    trajectory=trajectory,
                )

    async def generate_answers_batch(
        self,
        questions: list[NvIQuestion],
        matcher: SectionMatcher,
        supplementary_matcher: SupplementaryMatcher | None = None,
    ) -> AsyncIterator[GeneratedAnswer]:
        """Generate answers for a batch of questions concurrently.

        Args:
            questions: List of NvI questions
            matcher: Section matcher with loaded Inkoopbeleid sections
            supplementary_matcher: Optional matcher for supplementary documents

        Yields:
            GeneratedAnswer for each question (order not guaranteed)
        """
        tasks = [
            asyncio.create_task(self.generate_answer(q, matcher, supplementary_matcher))
            for q in questions
        ]

        for task in asyncio.as_completed(tasks):
            yield await task

    async def generate_all_answers(
        self,
        questions: list[NvIQuestion],
        matcher: SectionMatcher,
        supplementary_matcher: SupplementaryMatcher | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[GeneratedAnswer]:
        """Generate answers for all questions with progress tracking.

        Args:
            questions: List of NvI questions
            matcher: Section matcher with loaded Inkoopbeleid sections
            supplementary_matcher: Optional matcher for supplementary documents
            progress_callback: Optional callback(completed, total) for progress

        Returns:
            List of GeneratedAnswer objects
        """
        answers = []
        total = len(questions)
        completed = 0

        async for answer in self.generate_answers_batch(questions, matcher, supplementary_matcher):
            answers.append(answer)
            completed += 1
            if progress_callback:
                progress_callback(completed, total)

        # Sort by section number to maintain order
        answers.sort(key=lambda a: (a.section_nr or "", a.question))
        return answers
