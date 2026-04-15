"""Supplementary document matcher for cross-document keyword matching."""

import re
from dataclasses import dataclass

from .models import NvIQuestion, SupplementaryChunk


@dataclass
class SupplementaryMatchResult:
    """Result of supplementary document matching."""

    matched_chunks: list[SupplementaryChunk]
    match_details: str


class SupplementaryMatcher:
    """Keyword-based matching against supplementary reference documents."""

    STOPWORDS = {
        "de", "het", "een", "van", "in", "op", "te", "met", "voor", "aan",
        "dat", "die", "is", "zijn", "wordt", "worden", "bij", "ook", "als",
        "naar", "om", "uit", "tot", "kan", "over", "door", "maar", "nog",
        "wel", "niet", "dan", "zo", "u", "we", "wij", "uw", "dit", "deze",
        "er", "zich", "heeft", "hebben", "was", "waren", "zal", "zou",
    }

    MAX_CHUNKS = 3
    MAX_CONTEXT_CHARS = 4000

    def __init__(self, chunks: list[SupplementaryChunk]):
        self.chunks = chunks
        self._keyword_index: dict[str, list[SupplementaryChunk]] = {}
        self._build_keyword_index()

    def _build_keyword_index(self) -> None:
        """Build inverted index from keywords to chunks."""
        for chunk in self.chunks:
            text = f"{chunk.title} {chunk.text}".lower()
            words = re.findall(r"\b[a-zA-Z]{4,}\b", text)

            for word in words:
                if word not in self.STOPWORDS:
                    if word not in self._keyword_index:
                        self._keyword_index[word] = []
                    if chunk not in self._keyword_index[word]:
                        self._keyword_index[word].append(chunk)

    def match(self, question: NvIQuestion) -> SupplementaryMatchResult:
        """Find relevant supplementary chunks for a question."""
        text = question.question.lower()
        words = re.findall(r"\b[a-zA-Z]{4,}\b", text)

        chunk_scores: dict[int, int] = {}
        id_to_chunk: dict[int, SupplementaryChunk] = {}

        for word in words:
            if word in self._keyword_index:
                for chunk in self._keyword_index[word]:
                    cid = id(chunk)
                    chunk_scores[cid] = chunk_scores.get(cid, 0) + 1
                    id_to_chunk[cid] = chunk

        if not chunk_scores:
            return SupplementaryMatchResult([], "No supplementary matches found")

        sorted_chunks = sorted(
            chunk_scores.items(), key=lambda x: x[1], reverse=True
        )

        matched = []
        total_chars = 0
        for chunk_id, score in sorted_chunks[:self.MAX_CHUNKS]:
            chunk = id_to_chunk[chunk_id]
            if total_chars + len(chunk.text) > self.MAX_CONTEXT_CHARS and matched:
                break
            matched.append(chunk)
            total_chars += len(chunk.text)

        doc_ids = set(c.doc_id for c in matched)
        return SupplementaryMatchResult(
            matched_chunks=matched,
            match_details=f"Matched {len(matched)} chunks from {len(doc_ids)} documents",
        )

    def get_context_text(self, chunks: list[SupplementaryChunk]) -> str:
        """Format matched chunks as context text for the LLM."""
        if not chunks:
            return ""

        parts = []
        for chunk in chunks:
            label = f"[Bron: {chunk.doc_title}"
            if chunk.section:
                label += f" - {chunk.section}"
            if chunk.title and chunk.title != chunk.section:
                label += f" {chunk.title}"
            label += "]"
            parts.append(f"{label}\n{chunk.text}\n")

        return "\n".join(parts)
