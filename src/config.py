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

    # Improvement flags
    enable_maatwerk_examples: bool = False
    enable_quote_before_conclude: bool = False
    enable_verify_loop: bool = False
    enable_calibrated_confidence: bool = False
    enable_model_guided_retrieval: bool = False

    # Iteration 14 flags (ablation-ready)
    enable_nza_role_emphasis: bool = True
    enable_vv_few_shot: bool = True
    enable_section_citations: bool = True
    enable_collaborative_framing: bool = True

    def get_nvi_path(self, domain: str) -> Path:
        """Get path to NvI JSON file for a domain."""
        return self.parsed_data_path / f"NvI-{domain}-2024-2026.json"

    def get_inkoopbeleid_path(self, domain: str) -> Path:
        """Get path to Inkoopbeleid JSON file for a domain."""
        return self.parsed_data_path / f"Inkoopbeleid-{domain}-2024-2026.json"

    def get_supplementary_chunks_path(self) -> Path:
        """Get path to supplementary chunks JSON file."""
        return self.parsed_data_path / "extra" / "supplementary_chunks.json"

    def get_output_path(self, domain: str) -> Path:
        """Get path for output JSON file."""
        return self.output_path / f"{domain}_answers.json"

    class Config:
        arbitrary_types_allowed = True
