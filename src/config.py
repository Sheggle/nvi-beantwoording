"""Configuration settings for the NvI answering system."""

import os
from pathlib import Path
from pydantic import BaseModel, Field


class Settings(BaseModel):
    """Application settings."""

    # API Configuration
    openai_api_key: str = Field(default_factory=lambda: os.environ.get("OPENAI_API_KEY", ""))
    model: str = "gpt-4.1-mini"
    evaluation_model: str = "gpt-4.1-mini"

    # Rate limiting
    max_concurrent_requests: int = 10
    requests_per_minute: int = 60

    # Paths
    base_path: Path = Field(default_factory=lambda: Path(__file__).parent.parent)
    parsed_data_path: Path = Field(default_factory=lambda: Path(__file__).parent.parent / "parsed_data")
    output_path: Path = Field(default_factory=lambda: Path(__file__).parent.parent / "output")

    # Processing
    batch_size: int = 10

    def get_nvi_path(self, domain: str) -> Path:
        """Get path to NvI JSON file for a domain."""
        return self.parsed_data_path / f"NvI-{domain}-2024-2026.json"

    def get_inkoopbeleid_path(self, domain: str) -> Path:
        """Get path to Inkoopbeleid JSON file for a domain."""
        return self.parsed_data_path / f"Inkoopbeleid-{domain}-2024-2026.json"

    def get_output_path(self, domain: str) -> Path:
        """Get path for output JSON file."""
        return self.output_path / f"{domain}_answers.json"

    class Config:
        arbitrary_types_allowed = True
