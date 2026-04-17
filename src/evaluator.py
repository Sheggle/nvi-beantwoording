"""Post-hoc evaluation of generated answers against reference answers."""

import asyncio
import time
from typing import Callable

from openai import AsyncOpenAI

from .models import EvaluationResult, GeneratedAnswer
from .config import Settings, openai_client


class TokenBucket:
    """Simple token bucket for rate limiting."""

    def __init__(self, rate: float, capacity: float):
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self.last_update
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                self.last_update = now

                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return

                wait_time = (tokens - self.tokens) / self.rate
                await asyncio.sleep(wait_time)


class Evaluator:
    """Evaluates correspondence between generated and reference answers."""

    SYSTEM_PROMPT = """Je bent een evaluator die gegenereerde antwoorden vergelijkt met referentieantwoorden.

Beoordeel de correspondentie op een schaal van 1-5:
- 5: Inhoudelijk hetzelfde antwoord, zelfde conclusie
- 4: Zelfde richting, kleine verschillen in detail of formulering
- 3: Gedeeltelijke overlap, sommige kernpunten komen overeen
- 2: Andere benadering maar niet tegenstrijdig
- 1: Tegenstrijdig of compleet ander antwoord

Let op: het gaat om inhoudelijke correspondentie, niet om woordelijke overeenkomst.
Een kort referentieantwoord en een langer gegenereerd antwoord kunnen nog steeds score 5 krijgen als de conclusie hetzelfde is."""

    def __init__(self, settings: Settings | None = None, client: AsyncOpenAI | None = None):
        self.settings = settings or Settings()
        self.client = client or openai_client
        self._semaphore = asyncio.Semaphore(self.settings.max_concurrent_requests)
        self._token_bucket = TokenBucket(
            rate=self.settings.requests_per_minute / 60.0,
            capacity=self.settings.max_concurrent_requests,
        )

    async def evaluate_answer(self, answer: GeneratedAnswer) -> GeneratedAnswer:
        """Evaluate a single generated answer against its reference.

        Mutates the answer in-place by setting correspondence_score and
        evaluation_reasoning, and also returns it.
        """
        if not answer.original_answer:
            answer.correspondence_score = None
            answer.evaluation_reasoning = "Geen referentieantwoord beschikbaar"
            return answer

        user_prompt = f"""VRAAG:
{answer.question}

GEGENEREERD ANTWOORD:
{answer.answer}

REFERENTIEANTWOORD:
{answer.original_answer}"""

        await self._token_bucket.acquire()

        async with self._semaphore:
            try:
                response = await self.client.beta.chat.completions.parse(
                    model=self.settings.evaluation_model,
                    messages=[
                        {"role": "system", "content": self.SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format=EvaluationResult,
                    temperature=0.0,
                    max_tokens=300,
                )

                result = response.choices[0].message.parsed
                if result:
                    answer.correspondence_score = result.correspondence_score
                    answer.evaluation_reasoning = result.evaluation_reasoning
                else:
                    answer.correspondence_score = None
                    answer.evaluation_reasoning = "Lege response van LLM"

            except Exception as e:
                answer.correspondence_score = None
                answer.evaluation_reasoning = f"Evaluatiefout: {str(e)}"

        return answer

    async def evaluate_all_answers(
        self,
        answers: list[GeneratedAnswer],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[GeneratedAnswer]:
        """Evaluate all generated answers against their references.

        Args:
            answers: List of generated answers (with original_answer set)
            progress_callback: Optional callback(completed, total)

        Returns:
            The same list with correspondence scores filled in
        """
        tasks = [
            asyncio.create_task(self.evaluate_answer(a))
            for a in answers
        ]

        completed = 0
        total = len(tasks)

        for coro in asyncio.as_completed(tasks):
            await coro
            completed += 1
            if progress_callback:
                progress_callback(completed, total)

        return answers
