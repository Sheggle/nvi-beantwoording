"""Pydantic models for NvI question-answer mapping."""

from typing import Literal
from pydantic import BaseModel


# Literal type for structured outputs (OpenAI parses this correctly)
AnswerConfidence = Literal["high", "medium", "low", "unanswerable"]


class NvIQuestion(BaseModel):
    """A question from the Nota van Inlichtingen."""

    section: str
    question: str
    answer: str  # Original answer from NvI (for comparison)


class InkoopbeleidSection(BaseModel):
    """A section from the Inkoopbeleid document."""

    section: str
    title: str
    text: str


class GeneratedAnswer(BaseModel):
    """A generated answer for an NvI question."""

    section_nr: str
    question: str
    answer: str
    confidence: AnswerConfidence
    source_sections: list[str]
    reasoning: str | None = None
    original_answer: str | None = None  # For comparison
    correspondence_score: int | None = None
    evaluation_reasoning: str | None = None


class LLMResponse(BaseModel):
    """Expected response structure from the LLM."""

    answer: str
    confidence: AnswerConfidence
    source_sections: list[str]
    reasoning: str


class EvaluationResult(BaseModel):
    """Result of post-hoc correspondence evaluation."""

    correspondence_score: Literal[1, 2, 3, 4, 5]
    evaluation_reasoning: str
