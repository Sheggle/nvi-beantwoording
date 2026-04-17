"""Pipeline orchestration for the NvI answering system."""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Callable

from .models import GeneratedAnswer
from .config import Settings
from .data_loader import DataLoader
from .section_matcher import SectionMatcher
from .answer_generator import AnswerGenerator
from .supplementary_matcher import SupplementaryMatcher
from .evaluator import Evaluator


class Pipeline:
    """Orchestrates the full question-to-answer pipeline."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.data_loader = DataLoader(self.settings)
        self.answer_generator = AnswerGenerator(self.settings)
        self.evaluator = Evaluator(self.settings)

    async def process_domain(
        self,
        domain: str,
        limit: int | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[GeneratedAnswer]:
        """Process all questions for a domain.

        Args:
            domain: The domain code (e.g., 'GGZ', 'GZ', 'VV')
            limit: Optional limit on number of questions to process
            progress_callback: Optional callback(completed, total) for progress

        Returns:
            List of GeneratedAnswer objects
        """
        # Load data
        questions, sections = self.data_loader.load_domain_data(domain)

        # Load supplementary chunks (domain-independent)
        supplementary_chunks = self.data_loader.load_supplementary_chunks()
        supplementary_matcher = None
        if supplementary_chunks:
            supplementary_matcher = SupplementaryMatcher(supplementary_chunks)
            print(f"Loaded {len(supplementary_chunks)} supplementary chunks")

        if limit:
            questions = questions[:limit]

        print(f"Loaded {len(questions)} questions and {len(sections)} sections for {domain}")

        # Create section matcher
        matcher = SectionMatcher(sections)

        # Generate answers
        answers = await self.answer_generator.generate_all_answers(
            questions, matcher, supplementary_matcher, progress_callback
        )

        return answers

    def save_results(
        self,
        answers: list[GeneratedAnswer],
        domain: str,
        output_path: Path | None = None,
    ) -> Path:
        """Save results to JSON file.

        Args:
            answers: List of generated answers
            domain: Domain code for filename
            output_path: Optional custom output path

        Returns:
            Path to the saved file
        """
        if output_path is None:
            output_path = self.settings.get_output_path(domain)

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Build output data
        active_improvements = {
            "enable_maatwerk_examples": self.settings.enable_maatwerk_examples,
            "enable_quote_before_conclude": self.settings.enable_quote_before_conclude,
            "enable_verify_loop": self.settings.enable_verify_loop,
            "enable_calibrated_confidence": self.settings.enable_calibrated_confidence,
            "enable_model_guided_retrieval": self.settings.enable_model_guided_retrieval,
        }

        output_data = {
            "metadata": {
                "domain": domain,
                "generated_at": datetime.now().isoformat(),
                "total_questions": len(answers),
                "model": self.settings.model,
                "active_improvements": active_improvements,
            },
            "statistics": self._compute_statistics(answers),
            "answers": [a.model_dump() for a in answers],
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)

        print(f"Results saved to {output_path}")
        return output_path

    def _compute_statistics(self, answers: list[GeneratedAnswer]) -> dict:
        """Compute statistics about the generated answers."""
        total = len(answers)
        if total == 0:
            return {}

        confidence_counts = {"high": 0, "medium": 0, "low": 0, "unanswerable": 0}
        for answer in answers:
            confidence_counts[answer.confidence] += 1

        confidence_pcts = {
            k: round(v / total * 100, 1) for k, v in confidence_counts.items()
        }

        # Check for high unanswerable rate
        unanswerable_pct = confidence_pcts.get("unanswerable", 0)
        alert = unanswerable_pct > 30

        stats = {
            "confidence_counts": confidence_counts,
            "confidence_percentages": confidence_pcts,
            "alert_high_unanswerable": alert,
        }

        # Evaluation statistics
        scores = [a.correspondence_score for a in answers if a.correspondence_score is not None]
        if scores:
            score_distribution = {i: scores.count(i) for i in range(1, 6)}
            stats["evaluation_statistics"] = {
                "mean_correspondence": round(sum(scores) / len(scores), 2),
                "evaluated_count": len(scores),
                "score_distribution": score_distribution,
            }

        return stats

    def print_statistics(self, answers: list[GeneratedAnswer]) -> None:
        """Print statistics about the generated answers."""
        stats = self._compute_statistics(answers)
        if not stats:
            print("No answers to analyze")
            return

        print("\n=== Answer Statistics ===")
        print(f"Total questions: {len(answers)}")
        print("\nConfidence distribution:")
        for confidence, count in stats["confidence_counts"].items():
            pct = stats["confidence_percentages"][confidence]
            print(f"  {confidence}: {count} ({pct}%)")

        if stats["alert_high_unanswerable"]:
            print("\n[ALERT] More than 30% of questions are unanswerable!")

        if "evaluation_statistics" in stats:
            eval_stats = stats["evaluation_statistics"]
            print(f"\nCorrespondence evaluation ({eval_stats['evaluated_count']} evaluated):")
            print(f"  Mean score: {eval_stats['mean_correspondence']}/5")
            print("  Distribution:")
            for score, count in eval_stats["score_distribution"].items():
                print(f"    {score}: {count}")

    async def run(
        self,
        domain: str,
        limit: int | None = None,
        save: bool = True,
        evaluate: bool = True,
    ) -> list[GeneratedAnswer]:
        """Run the full pipeline for a domain.

        Args:
            domain: The domain code (e.g., 'GGZ', 'GZ', 'VV')
            limit: Optional limit on number of questions to process
            save: Whether to save results to file
            evaluate: Whether to run post-hoc correspondence evaluation

        Returns:
            List of GeneratedAnswer objects
        """
        def progress(completed: int, total: int) -> None:
            print(f"\rProcessing: {completed}/{total} ({completed/total*100:.1f}%)", end="", flush=True)

        def eval_progress(completed: int, total: int) -> None:
            print(f"\rEvaluating: {completed}/{total} ({completed/total*100:.1f}%)", end="", flush=True)

        print(f"Starting pipeline for domain: {domain}")
        answers = await self.process_domain(domain, limit, progress)
        print()  # Newline after progress

        if evaluate:
            print("Starting post-hoc evaluation...")
            await self.evaluator.evaluate_all_answers(answers, eval_progress)
            print()  # Newline after progress

        self.print_statistics(answers)

        if save:
            self.save_results(answers, domain)

        return answers


async def main():
    """Main entry point for running the pipeline."""
    import sys

    # Default to GGZ (smallest domain with 202 questions)
    domain = sys.argv[1] if len(sys.argv) > 1 else "GGZ"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None

    settings = Settings()

    # List available domains
    available = DataLoader.list_available_domains(settings.parsed_data_path)
    print(f"Available domains: {', '.join(available)}")

    if domain not in available:
        print(f"Error: Domain '{domain}' not found")
        sys.exit(1)

    pipeline = Pipeline(settings)
    await pipeline.run(domain, limit)


if __name__ == "__main__":
    asyncio.run(main())
