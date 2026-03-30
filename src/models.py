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


class VerificationResponse(BaseModel):
    """Response from the verify-after-generate loop."""

    claims: list[str]
    unsupported_claims: list[str]
    revised_answer: str
    revision_reasoning: str


class Trajectory(BaseModel):
    """Per-question trajectory capturing the full agent trace."""

    match_type: str | None = None  # e.g. "direct", "parent", "keyword"
    match_details: str | None = None
    matched_inkoopbeleid_sections: list[str] = []
    matched_supplementary_chunks: list[dict] = []  # [{doc_id, section, title}]
    full_prompt: str | None = None  # The complete user prompt sent to the LLM
    raw_response: dict | None = None  # Raw LLM response
    active_improvements: list[str] = []
    verification_response: dict | None = None
    retrieval_tool_calls: list[dict] = []


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
    trajectory: Trajectory | None = None


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


class SupplementaryChunk(BaseModel):
    """A chunk from a supplementary reference document."""

    doc_id: str
    doc_title: str
    source: str  # "nza" or "zk"
    section: str
    title: str
    text: str
