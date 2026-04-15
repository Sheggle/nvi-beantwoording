"""Evaluate the pipeline against expert feedback scores.

Usage:
    uv run python scripts/eval_feedback.py              # Run all scored questions (39 total)
    uv run python scripts/eval_feedback.py --domain GGZ  # Only GGZ (10 questions)
    uv run python scripts/eval_feedback.py --domain GZ   # Only GZ (17 questions)
    uv run python scripts/eval_feedback.py --domain VV   # Only VV (12 questions)

Loads expert-scored questions from feedback/*.xlsx, runs the pipeline,
and compares generated answers against expert scores. Prints per-question
results and aggregate statistics.
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import Settings
from src.data_loader import DataLoader
from src.section_matcher import SectionMatcher
from src.supplementary_matcher import SupplementaryMatcher
from src.answer_generator import AnswerGenerator
from src.evaluator import Evaluator
from src.models import NvIQuestion

FEEDBACK_DIR = Path(__file__).parent.parent / "feedback"

# Feedback file configs: (filename, score_column, comment_column, answer_col)
FEEDBACK_FILES = {
    "GZ": ("GZ_antwoorden_1emodel.xlsx", "Beoordeling inhoud (1-5)", "Opmerkingen", "original_answer"),
    "GGZ": ("GGZ_antwoorden_1emodel.xlsx", "Beoordeling inhoud (1-5)", "Opmerking", "original_answer"),
    "VV": ("VV_antwoorden_eerstemodel.xlsx", "Beoordeling_inhoud", "Opmerkingen", "original_answer"),
}


def load_feedback_questions(domain: str) -> list[dict]:
    """Load expert-scored questions from feedback Excel.

    Returns list of {question, original_answer, section_nr, expert_score, expert_comment}.
    Only questions with a score are included.
    """
    fname, score_col, comment_col, answer_col = FEEDBACK_FILES[domain]
    df = pd.read_excel(FEEDBACK_DIR / fname, sheet_name="Sheet1")

    scored = df[df[score_col].notna()].copy()
    items = []
    for _, row in scored.iterrows():
        items.append({
            "question": str(row["question"]),
            "original_answer": str(row[answer_col]),
            "section_nr": str(row.get("section_nr", "")) if pd.notna(row.get("section_nr")) else "",
            "expert_score": int(row[score_col]),
            "expert_comment": str(row.get(comment_col, "")) if pd.notna(row.get(comment_col)) else "",
        })
    return items


async def run_eval(domains: list[str], settings: Settings) -> dict:
    """Run pipeline on all expert-scored questions and compare."""
    loader = DataLoader(settings)
    all_results = []

    for domain in domains:
        feedback = load_feedback_questions(domain)
        if not feedback:
            print(f"  {domain}: no scored questions, skipping")
            continue

        # Load domain data
        sections = loader.load_inkoopbeleid_sections(domain)
        matcher = SectionMatcher(sections)
        supp_chunks = loader.load_supplementary_chunks()
        supp_matcher = SupplementaryMatcher(supp_chunks) if supp_chunks else None

        # Convert to NvIQuestion
        questions = [
            NvIQuestion(
                section=item["section_nr"],
                question=item["question"],
                answer=item["original_answer"],
            )
            for item in feedback
        ]

        print(f"\n  {domain}: generating {len(questions)} answers...")
        generator = AnswerGenerator(settings)
        evaluator = Evaluator(settings)

        answers = await generator.generate_all_answers(
            questions, matcher, supp_matcher,
            progress_callback=lambda c, t: print(f"\r  {domain}: {c}/{t}", end="", flush=True),
        )
        print()

        print(f"  {domain}: evaluating...")
        await evaluator.evaluate_all_answers(
            answers,
            progress_callback=lambda c, t: print(f"\r  {domain}: eval {c}/{t}", end="", flush=True),
        )
        print()

        # Match answers back to feedback by question text
        answer_map = {a.question: a for a in answers}

        for item in feedback:
            a = answer_map.get(item["question"])
            if not a:
                continue
            all_results.append({
                "domain": domain,
                "question": item["question"][:100],
                "expert_score": item["expert_score"],
                "expert_comment": item["expert_comment"],
                "ai_score": a.correspondence_score,
                "ai_confidence": a.confidence,
                "ai_answer": a.answer[:200],
                "section_nr": item["section_nr"],
            })

    return {
        "timestamp": datetime.now().isoformat(),
        "settings": {
            "model": settings.model,
            "enable_maatwerk_examples": settings.enable_maatwerk_examples,
            "enable_quote_before_conclude": settings.enable_quote_before_conclude,
            "enable_verify_loop": settings.enable_verify_loop,
            "enable_calibrated_confidence": settings.enable_calibrated_confidence,
            "enable_model_guided_retrieval": settings.enable_model_guided_retrieval,
        },
        "domains": domains,
        "total_questions": len(all_results),
        "results": all_results,
    }


def print_results(data: dict) -> None:
    """Print evaluation results."""
    results = data["results"]
    if not results:
        print("No results to display.")
        return

    expert_scores = [r["expert_score"] for r in results]
    ai_scores = [r["ai_score"] for r in results if r["ai_score"] is not None]

    print(f"\n{'='*80}")
    print(f"EVALUATION RESULTS ({len(results)} expert-scored questions)")
    print(f"{'='*80}")

    # Per-question detail
    for r in sorted(results, key=lambda x: x["expert_score"]):
        expert = r["expert_score"]
        ai = r["ai_score"] or "?"
        domain = r["domain"]
        q = r["question"][:70]
        comment = r["expert_comment"][:50] if r["expert_comment"] else ""
        print(f"  [{domain}] expert={expert} ai={ai} | {q}")
        if comment:
            print(f"         comment: {comment}")

    # Aggregate
    print(f"\n{'='*80}")
    mean_expert = sum(expert_scores) / len(expert_scores)
    mean_ai = sum(ai_scores) / len(ai_scores) if ai_scores else 0
    print(f"  Expert mean: {mean_expert:.2f}")
    print(f"  AI eval mean: {mean_ai:.2f}")

    # Correlation: how often does AI eval agree with expert?
    agree = sum(1 for r in results if r["ai_score"] == r["expert_score"])
    close = sum(1 for r in results if r["ai_score"] is not None and abs(r["ai_score"] - r["expert_score"]) <= 1)
    print(f"  Exact agreement: {agree}/{len(results)} ({agree/len(results)*100:.0f}%)")
    print(f"  Within ±1: {close}/{len(results)} ({close/len(results)*100:.0f}%)")

    # Score distribution
    from collections import Counter
    expert_dist = Counter(expert_scores)
    print(f"  Expert distribution: {dict(sorted(expert_dist.items()))}")
    if ai_scores:
        ai_dist = Counter(ai_scores)
        print(f"  AI eval distribution: {dict(sorted(ai_dist.items()))}")
    print(f"{'='*80}")


async def main():
    args = sys.argv[1:]
    domain_filter = None
    if "--domain" in args:
        idx = args.index("--domain")
        domain_filter = args[idx + 1].upper()
        args = args[:idx] + args[idx + 2:]

    domains = [domain_filter] if domain_filter else ["GGZ", "GZ", "VV"]

    settings = Settings()
    if not settings.openai_api_key:
        print("Error: OPENAI_API_KEY not set")
        sys.exit(1)

    print(f"Evaluating against expert feedback for domains: {', '.join(domains)}")
    data = await run_eval(domains, settings)
    print_results(data)

    # Save
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = output_dir / f"feedback_eval_{timestamp}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\nDetailed results saved to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
