"""Data loader for NvI and Inkoopbeleid JSON files."""

import json
from pathlib import Path

from .models import NvIQuestion, InkoopbeleidSection, SupplementaryChunk
from .config import Settings


class DataLoader:
    """Loads and parses NvI questions and Inkoopbeleid sections."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()

    def load_nvi_questions(self, domain: str) -> list[NvIQuestion]:
        """Load NvI questions for a specific domain.

        Args:
            domain: The domain code (e.g., 'GGZ', 'GZ', 'VV')

        Returns:
            List of NvIQuestion objects
        """
        path = self.settings.get_nvi_path(domain)
        return self._load_nvi_from_path(path)

    def _load_nvi_from_path(self, path: Path) -> list[NvIQuestion]:
        """Load NvI questions from a specific path."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return [NvIQuestion(**item) for item in data]

    def load_inkoopbeleid_sections(self, domain: str) -> list[InkoopbeleidSection]:
        """Load Inkoopbeleid sections for a specific domain.

        Args:
            domain: The domain code (e.g., 'GGZ', 'GZ', 'VV')

        Returns:
            List of InkoopbeleidSection objects
        """
        path = self.settings.get_inkoopbeleid_path(domain)
        return self._load_inkoopbeleid_from_path(path)

    def _load_inkoopbeleid_from_path(self, path: Path) -> list[InkoopbeleidSection]:
        """Load Inkoopbeleid sections from a specific path."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return [InkoopbeleidSection(**item) for item in data]

    def load_domain_data(
        self, domain: str
    ) -> tuple[list[NvIQuestion], list[InkoopbeleidSection]]:
        """Load both NvI questions and Inkoopbeleid sections for a domain.

        Args:
            domain: The domain code (e.g., 'GGZ', 'GZ', 'VV')

        Returns:
            Tuple of (questions, sections)
        """
        questions = self.load_nvi_questions(domain)
        sections = self.load_inkoopbeleid_sections(domain)
        return questions, sections

    def load_supplementary_chunks(self) -> list[SupplementaryChunk]:
        """Load supplementary reference document chunks.

        Returns empty list if file not found.
        """
        path = self.settings.get_supplementary_chunks_path()
        if not path.exists():
            return []
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [SupplementaryChunk(**item) for item in data]

    @staticmethod
    def list_available_domains(parsed_data_path: Path) -> list[str]:
        """List available domains based on parsed data files.

        Args:
            parsed_data_path: Path to the parsed_data directory

        Returns:
            List of domain codes
        """
        domains = set()
        for path in parsed_data_path.glob("NvI-*-2024-2026.json"):
            # Extract domain from filename like NvI-GGZ-2024-2026.json
            parts = path.stem.split("-")
            if len(parts) >= 2:
                domains.add(parts[1])
        return sorted(domains)
