"""Async OpenAI-based answer generator with rate limiting."""

import asyncio
import time
from typing import AsyncIterator, Callable

from openai import AsyncOpenAI

from .models import (
    GeneratedAnswer,
    LLMResponse,
    NvIQuestion,
)
from .config import Settings
from .section_matcher import SectionMatcher, MatchResult


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

    SYSTEM_PROMPT = """Je bent een expert op het gebied van het zorginkoopbeleid van Zilveren Kruis voor de Wet langdurige zorg (Wlz).

Je taak is om vragen uit de Nota van Inlichtingen te beantwoorden op basis van de verstrekte beleidstekst.

Richtlijnen:
- Beantwoord de vraag met informatie uit de verstrekte beleidstekst
- Geef een nuttig antwoord waar mogelijk, ook als niet alle details expliciet vermeld staan
- Als specifieke details ontbreken, geef aan wat WEL in de tekst staat en wat ontbreekt
- Wees accuraat en verwijs naar specifieke secties
- Schrijf in het Nederlands, beknopt maar volledig

Betrouwbaarheidsniveaus:
- high: De kernvraag kan worden beantwoord met de tekst
- medium: Relevante informatie beschikbaar, maar belangrijke onderdelen ontbreken
- low: Alleen zijdelings gerelateerde informatie beschikbaar
- unanswerable: Geen relevante informatie in de tekst"""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.client = AsyncOpenAI(api_key=self.settings.openai_api_key)
        self._semaphore = asyncio.Semaphore(self.settings.max_concurrent_requests)
        self._token_bucket = TokenBucket(
            rate=self.settings.requests_per_minute / 60.0,
            capacity=self.settings.max_concurrent_requests,
        )

    def _build_user_prompt(
        self,
        question: NvIQuestion,
        context: str,
        match_result: MatchResult,
    ) -> str:
        """Build the user prompt for the LLM."""
        section_info = f" (sectie {question.section})" if question.section else ""

        if not context:
            return f"""BELEIDSTEKST:
Geen relevante secties gevonden in het inkoopbeleid.

VRAAG{section_info}:
{question.question}

Geef aan dat deze vraag niet beantwoord kan worden op basis van het beschikbare inkoopbeleid."""

        return f"""BELEIDSTEKST:
{context}

VRAAG{section_info}:
{question.question}"""

    async def generate_answer(
        self,
        question: NvIQuestion,
        matcher: SectionMatcher,
    ) -> GeneratedAnswer:
        """Generate an answer for a single question.

        Args:
            question: The NvI question to answer
            matcher: Section matcher with loaded Inkoopbeleid sections

        Returns:
            GeneratedAnswer with the response
        """
        # Match question to relevant sections
        match_result = matcher.match(question)

        # Build context from matched sections
        context = matcher.get_context_text(match_result.matched_sections)

        # Handle case where no sections matched
        if not match_result.matched_sections:
            return GeneratedAnswer(
                section_nr=question.section,
                question=question.question,
                answer="Deze vraag kan niet worden beantwoord op basis van het beschikbare inkoopbeleid. Er zijn geen relevante secties gevonden.",
                confidence="unanswerable",
                source_sections=[],
                reasoning=f"Geen match gevonden: {match_result.match_details}",
                original_answer=question.answer,
            )

        # Rate limiting
        await self._token_bucket.acquire()

        async with self._semaphore:
            try:
                # Use structured outputs with Pydantic model
                response = await self.client.beta.chat.completions.parse(
                    model=self.settings.model,
                    messages=[
                        {"role": "system", "content": self.SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": self._build_user_prompt(
                                question, context, match_result
                            ),
                        },
                    ],
                    response_format=LLMResponse,
                    temperature=0.1,
                    max_tokens=1000,
                )

                # Response is already parsed into LLMResponse
                llm_response = response.choices[0].message.parsed
                if llm_response:
                    return GeneratedAnswer(
                        section_nr=question.section,
                        question=question.question,
                        answer=llm_response.answer,
                        confidence=llm_response.confidence,
                        source_sections=llm_response.source_sections,
                        reasoning=llm_response.reasoning,
                        original_answer=question.answer,
                    )
                else:
                    raise ValueError("Empty response from LLM")

            except Exception as e:
                return GeneratedAnswer(
                    section_nr=question.section,
                    question=question.question,
                    answer=f"Fout bij het genereren van antwoord: {str(e)}",
                    confidence="unanswerable",
                    source_sections=[],
                    reasoning=f"API error: {str(e)}",
                    original_answer=question.answer,
                )

    async def generate_answers_batch(
        self,
        questions: list[NvIQuestion],
        matcher: SectionMatcher,
    ) -> AsyncIterator[GeneratedAnswer]:
        """Generate answers for a batch of questions concurrently.

        Args:
            questions: List of NvI questions
            matcher: Section matcher with loaded Inkoopbeleid sections

        Yields:
            GeneratedAnswer for each question (order not guaranteed)
        """
        tasks = [
            asyncio.create_task(self.generate_answer(q, matcher))
            for q in questions
        ]

        for task in asyncio.as_completed(tasks):
            yield await task

    async def generate_all_answers(
        self,
        questions: list[NvIQuestion],
        matcher: SectionMatcher,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[GeneratedAnswer]:
        """Generate answers for all questions with progress tracking.

        Args:
            questions: List of NvI questions
            matcher: Section matcher with loaded Inkoopbeleid sections
            progress_callback: Optional callback(completed, total) for progress

        Returns:
            List of GeneratedAnswer objects
        """
        answers = []
        total = len(questions)
        completed = 0

        async for answer in self.generate_answers_batch(questions, matcher):
            answers.append(answer)
            completed += 1
            if progress_callback:
                progress_callback(completed, total)

        # Sort by section number to maintain order
        answers.sort(key=lambda a: (a.section_nr or "", a.question))
        return answers
