"""Evaluate the pipeline against the golden set.

Usage:
    uv run python scripts/eval_golden.py              # Run all 20 golden questions
    uv run python scripts/eval_golden.py --domain GGZ  # Only GGZ questions

Runs the pipeline on golden set questions, then uses an LLM judge to check
each key_assertion against the generated answer. Reports pass/fail per
assertion and per question.
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import Settings
from src.data_loader import DataLoader
from src.section_matcher import SectionMatcher
from src.supplementary_matcher import SupplementaryMatcher
from src.answer_generator import AnswerGenerator
from src.models import NvIQuestion

GOLDEN_SET_PATH = Path(__file__).parent.parent / "golden_set.json"


def load_golden_set(domain_filter: str | None = None) -> list[dict]:
    with open(GOLDEN_SET_PATH) as f:
        gs = json.load(f)
    if domain_filter:
        gs = [q for q in gs if q["domain"] == domain_filter]
    return gs


async def check_assertions(
    answer_text: str,
    golden: dict,
    settings: Settings,
) -> list[dict]:
    """Use LLM to check each key_assertion against the generated answer.

    Returns list of {assertion, passed, reasoning}.
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    results = []

    for assertion in golden["key_assertions"]:
        prompt = f"""\
Je bent een beoordelaar van antwoorden op vragen over zorginkoop.

**Vraag:** {golden['question'][:300]}

**Gegenereerd antwoord:** {answer_text}

**Criterium:** {assertion}

Voldoet het gegenereerde antwoord aan dit criterium? Antwoord met ALLEEN:
- "JA" als het criterium duidelijk is vervuld
- "NEE" als het criterium niet is vervuld
- Gevolgd door een korte toelichting (1 zin)

Voorbeeld: "JA — het antwoord verwijst naar sectie 2.3.2"
Voorbeeld: "NEE — het antwoord noemt bijlage 7 niet"
"""

        response = await client.chat.completions.create(
            model=settings.evaluation_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0,
        )

        reply = response.choices[0].message.content.strip()
        passed = reply.upper().startswith("JA")
        results.append({
            "assertion": assertion,
            "passed": passed,
            "reasoning": reply,
        })

    return results


async def run_golden_eval(settings: Settings, domain_filter: str | None = None) -> dict:
    """Run full golden set evaluation."""
    loader = DataLoader(settings)
    golden_set = load_golden_set(domain_filter)

    if not golden_set:
        print("No golden set questions found.")
        return {}

    # Group by domain
    domains = sorted(set(q["domain"] for q in golden_set))
    print(f"Evaluating {len(golden_set)} golden questions across domains: {', '.join(domains)}")

    all_results = []

    for domain in domains:
        domain_qs = [q for q in golden_set if q["domain"] == domain]
        if not domain_qs:
            continue

        sections = loader.load_inkoopbeleid_sections(domain)
        matcher = SectionMatcher(sections)
        supp_chunks = loader.load_supplementary_chunks()
        supp_matcher = SupplementaryMatcher(supp_chunks) if supp_chunks else None

        nvi_questions = [
            NvIQuestion(
                section=q.get("section_nr", ""),
                question=q["question"],
                answer=q["golden_answer"],
            )
            for q in domain_qs
        ]

        print(f"\n  {domain}: generating {len(nvi_questions)} answers...")
        generator = AnswerGenerator(settings)
        answers = await generator.generate_all_answers(
            nvi_questions, matcher, supp_matcher,
            progress_callback=lambda c, t: print(f"\r  {domain}: {c}/{t}", end="", flush=True),
        )
        print()

        answer_map = {a.question: a for a in answers}

        print(f"  {domain}: checking assertions...")
        for golden in domain_qs:
            a = answer_map.get(golden["question"])
            if not a:
                continue

            assertion_results = await check_assertions(a.answer, golden, settings)
            passed = sum(1 for r in assertion_results if r["passed"])
            total = len(assertion_results)

            all_results.append({
                "id": golden["id"],
                "domain": domain,
                "section_nr": golden.get("section_nr", ""),
                "question": golden["question"][:100],
                "golden_answer": golden["golden_answer"][:200],
                "generated_answer": a.answer[:200],
                "confidence": a.confidence,
                "assertions_passed": passed,
                "assertions_total": total,
                "assertion_details": assertion_results,
            })

    return {
        "timestamp": datetime.now().isoformat(),
        "commit": _get_git_hash(),
        "settings": {
            "model": settings.model,
            "enable_maatwerk_examples": settings.enable_maatwerk_examples,
            "enable_quote_before_conclude": settings.enable_quote_before_conclude,
            "enable_verify_loop": settings.enable_verify_loop,
            "enable_calibrated_confidence": settings.enable_calibrated_confidence,
            "enable_model_guided_retrieval": settings.enable_model_guided_retrieval,
        },
        "total_questions": len(all_results),
        "total_assertions_passed": sum(r["assertions_passed"] for r in all_results),
        "total_assertions": sum(r["assertions_total"] for r in all_results),
        "results": all_results,
    }


def _get_git_hash() -> str:
    import subprocess
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def print_results(data: dict) -> None:
    results = data["results"]
    if not results:
        print("No results.")
        return

    total_passed = data["total_assertions_passed"]
    total_assertions = data["total_assertions"]
    pct = total_passed / total_assertions * 100 if total_assertions else 0

    print(f"\n{'='*80}")
    print(f"GOLDEN SET EVALUATION — {data['commit']}")
    print(f"Assertions passed: {total_passed}/{total_assertions} ({pct:.0f}%)")
    print(f"{'='*80}")

    for r in results:
        passed = r["assertions_passed"]
        total = r["assertions_total"]
        status = "PASS" if passed == total else "FAIL"
        marker = "  " if status == "PASS" else ">>"
        print(f"{marker} {r['id']} [{r['domain']}] {passed}/{total} | {r['question'][:60]}")
        for ad in r["assertion_details"]:
            check = "+" if ad["passed"] else "X"
            print(f"     [{check}] {ad['assertion'][:70]}")
            if not ad["passed"]:
                print(f"         {ad['reasoning'][:80]}")

    print(f"\n{'='*80}")
    print(f"TOTAL: {total_passed}/{total_assertions} assertions passed ({pct:.0f}%)")

    # Per-domain breakdown
    from collections import defaultdict
    by_domain = defaultdict(lambda: {"passed": 0, "total": 0})
    for r in results:
        by_domain[r["domain"]]["passed"] += r["assertions_passed"]
        by_domain[r["domain"]]["total"] += r["assertions_total"]
    for d, counts in sorted(by_domain.items()):
        dp = counts["passed"] / counts["total"] * 100 if counts["total"] else 0
        print(f"  {d}: {counts['passed']}/{counts['total']} ({dp:.0f}%)")
    print(f"{'='*80}")


async def main():
    args = sys.argv[1:]
    domain_filter = None
    if "--domain" in args:
        idx = args.index("--domain")
        domain_filter = args[idx + 1].upper()

    settings = Settings()
    if not settings.openai_api_key:
        print("Error: OPENAI_API_KEY not set")
        sys.exit(1)

    data = await run_golden_eval(settings, domain_filter)
    print_results(data)

    # Save
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = output_dir / f"golden_eval_{timestamp}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
