"""Section matcher for mapping NvI questions to Inkoopbeleid sections."""

import re
from dataclasses import dataclass

from .models import NvIQuestion, InkoopbeleidSection


@dataclass
class MatchResult:
    """Result of section matching."""

    matched_sections: list[InkoopbeleidSection]
    match_type: str  # 'direct', 'subsection', 'parent', 'keyword', 'none'
    match_details: str


class SectionMatcher:
    """Multi-tier matching strategy to find relevant Inkoopbeleid sections."""

    def __init__(self, sections: list[InkoopbeleidSection]):
        self.sections = sections
        self._section_index = {s.section: s for s in sections}
        self._build_keyword_index()

    def _build_keyword_index(self) -> None:
        """Build an index for keyword-based searching."""
        self._keyword_index: dict[str, list[InkoopbeleidSection]] = {}

        # Common Dutch stopwords to exclude
        stopwords = {
            "de", "het", "een", "van", "in", "op", "te", "met", "voor", "aan",
            "dat", "die", "is", "zijn", "wordt", "worden", "bij", "ook", "als",
            "naar", "om", "uit", "tot", "kan", "over", "door", "maar", "nog",
            "wel", "niet", "dan", "zo", "u", "we", "wij", "uw", "dit", "deze",
            "er", "zich", "heeft", "hebben", "was", "waren", "zal", "zou",
        }

        for section in self.sections:
            # Extract words from title and text
            text = f"{section.title} {section.text}".lower()
            words = re.findall(r"\b[a-zA-Z]{4,}\b", text)

            for word in words:
                if word not in stopwords:
                    if word not in self._keyword_index:
                        self._keyword_index[word] = []
                    if section not in self._keyword_index[word]:
                        self._keyword_index[word].append(section)

    def match(self, question: NvIQuestion) -> MatchResult:
        """Find relevant Inkoopbeleid sections for a question.

        Uses multi-tier matching strategy:
        1. Direct match: NvI section "1.2" -> Inkoopbeleid "1.2"
        2. Subsection expansion: "1.2" -> include "1.2.1", "1.2.2"
        3. Parent fallback: If "1.4.5" not found -> try "1.4"
        4. Keyword fallback: Extract key terms -> search all sections
        """
        section_nr = question.section.strip()

        # If no section number, go straight to keyword matching
        if not section_nr:
            return self._keyword_match(question)

        # Tier 1: Direct match + subsections (always include subsections for more context)
        direct_result = self._direct_match_with_subsections(section_nr)
        if direct_result.matched_sections:
            return direct_result

        # Tier 3: Parent fallback
        parent_result = self._parent_match(section_nr)
        if parent_result.matched_sections:
            return parent_result

        # Tier 4: Keyword fallback
        return self._keyword_match(question)

    def _direct_match_with_subsections(self, section_nr: str) -> MatchResult:
        """Tier 1: Direct match plus all subsections for richer context."""
        prefix = f"{section_nr}."
        matched = []

        # Add exact match first
        if section_nr in self._section_index:
            matched.append(self._section_index[section_nr])

        # Add all subsections
        for s in self.sections:
            if s.section.startswith(prefix) and s not in matched:
                matched.append(s)

        if matched:
            return MatchResult(
                matched_sections=matched,
                match_type="direct",
                match_details=f"Direct match for {section_nr} with {len(matched)} sections (incl. subsections)",
            )
        return MatchResult([], "none", f"No direct match for {section_nr}")

    def _subsection_match(self, section_nr: str) -> MatchResult:
        """Tier 2: Find all subsections of the given section."""
        prefix = f"{section_nr}."
        matched = [
            s for s in self.sections
            if s.section.startswith(prefix) or s.section == section_nr
        ]

        if matched:
            return MatchResult(
                matched_sections=matched,
                match_type="subsection",
                match_details=f"Subsection expansion for {section_nr}: found {len(matched)} sections",
            )
        return MatchResult([], "none", f"No subsections for {section_nr}")

    def _parent_match(self, section_nr: str) -> MatchResult:
        """Tier 3: Try parent section(s) if specific section not found."""
        parts = section_nr.split(".")
        matched = []

        # Try progressively shorter parent sections
        while len(parts) > 1:
            parts = parts[:-1]
            parent_nr = ".".join(parts)

            if parent_nr in self._section_index:
                matched.append(self._section_index[parent_nr])

            # Also get subsections of parent
            prefix = f"{parent_nr}."
            for s in self.sections:
                if s.section.startswith(prefix) and s not in matched:
                    matched.append(s)

            if matched:
                return MatchResult(
                    matched_sections=matched,
                    match_type="parent",
                    match_details=f"Parent fallback from {section_nr} to {parent_nr}: found {len(matched)} sections",
                )

        return MatchResult([], "none", f"No parent sections for {section_nr}")

    def _keyword_match(self, question: NvIQuestion) -> MatchResult:
        """Tier 4: Keyword-based matching from question text."""
        # Extract keywords from question
        text = question.question.lower()
        words = re.findall(r"\b[a-zA-Z]{4,}\b", text)

        # Count section relevance based on keyword overlap
        section_scores: dict[str, int] = {}
        matched_keywords: dict[str, list[str]] = {}

        for word in words:
            if word in self._keyword_index:
                for section in self._keyword_index[word]:
                    if section.section not in section_scores:
                        section_scores[section.section] = 0
                        matched_keywords[section.section] = []
                    section_scores[section.section] += 1
                    if word not in matched_keywords[section.section]:
                        matched_keywords[section.section].append(word)

        if not section_scores:
            return MatchResult(
                [],
                "none",
                "No keyword matches found",
            )

        # Sort by score and take top sections (max 5)
        sorted_sections = sorted(
            section_scores.items(), key=lambda x: x[1], reverse=True
        )[:5]

        matched = [self._section_index[s[0]] for s in sorted_sections]
        top_section = sorted_sections[0][0]
        keywords = matched_keywords[top_section][:5]

        return MatchResult(
            matched_sections=matched,
            match_type="keyword",
            match_details=f"Keyword match: {len(matched)} sections, top keywords: {', '.join(keywords)}",
        )

    def get_context_text(self, sections: list[InkoopbeleidSection]) -> str:
        """Format matched sections as context text for the LLM.

        Args:
            sections: List of matched sections

        Returns:
            Formatted context string
        """
        if not sections:
            return ""

        context_parts = []
        total_chars = 0

        for section in sections:
            section_text = f"[Sectie {section.section}] {section.title}\n{section.text}\n"

            context_parts.append(section_text)
            total_chars += len(section_text)

        return "\n".join(context_parts)
