"""Evaluate the pipeline against the full NvI question set.

Uses the expert answer as reference and an LLM judge to score
generated answers on a 0-3 scale.

Usage:
    uv run python scripts/eval_full.py
    uv run python scripts/eval_full.py --domain GZ
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import Settings
from src.data_loader import DataLoader
from src.section_matcher import SectionMatcher
from src.supplementary_matcher import SupplementaryMatcher
from src.answer_generator import AnswerGenerator
from src.models import NvIQuestion

import re


def clean_expert_answer(text: str) -> str:
    """Clean OCR artifacts from expert answers."""
    # Remove random single/double chars surrounded by spaces (OCR noise)
    text = re.sub(r'\s[a-z]{1,3}\s{2,}', ' ', text)
    # Collapse multiple spaces
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()


def is_corrupt_expert_answer(text: str) -> bool:
    """Detect corrupt/truncated expert answers."""
    text = text.strip()
    if len(text) < 15:
        return True
    if text.count('  ') > 3:
        return True
    return False


async def judge_answer(
    question: str,
    expert_answer: str,
    generated_answer: str,
    settings: Settings,
) -> dict:
    """Use LLM to compare generated answer against expert answer.

    Returns {score: 0-3, reasoning: str}.
    Score: 0=wrong/irrelevant, 1=partially correct, 2=mostly correct, 3=fully correct.
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)

    prompt = f"""\
Je vergelijkt een gegenereerd antwoord met het expert-antwoord op een vraag over zorginkoop.

**Vraag:** {question[:500]}

**Expert-antwoord (referentie):** {expert_answer[:500]}

**Gegenereerd antwoord:** {generated_answer[:500]}

Beoordeel het gegenereerde antwoord op een schaal van 0-3:
- 3: Volledig correct — alle kernpunten uit het expert-antwoord zijn aanwezig, geen fouten.
- 2: Grotendeels correct — de hoofdlijn klopt, maar 1-2 details ontbreken of zijn onnauwkeurig.
- 1: Gedeeltelijk correct — de richting klopt maar belangrijke informatie ontbreekt of is onjuist.
- 0: Onjuist of irrelevant — het antwoord is fout, misleidend, of beantwoordt de vraag niet.

Antwoord ALLEEN met het cijfer (0, 1, 2, of 3) gevolgd door een korte toelichting (max 1 zin).
Voorbeeld: "3 — alle kernpunten correct weergegeven"
Voorbeeld: "1 — juiste richting maar mist de verwijzing naar sectie 2.3"
"""

    response = await client.chat.completions.create(
        model=settings.evaluation_model,
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=100,
        temperature=0,
    )

    reply = response.choices[0].message.content.strip()
    try:
        score = int(reply[0])
        if score not in (0, 1, 2, 3):
            score = 0
    except (ValueError, IndexError):
        score = 0

    return {"score": score, "reasoning": reply}


async def run_full_eval(settings: Settings, domain_filter: str | None = None, clean_data: bool = True) -> dict:
    loader = DataLoader(settings)
    domains = ["GGZ", "GZ", "VV"]
    if domain_filter:
        domains = [domain_filter]

    all_results = []

    for domain in domains:
        nvi_path = settings.get_nvi_path(domain)
        if not nvi_path.exists():
            print(f"  {domain}: NvI file not found, skipping")
            continue

        with open(nvi_path) as f:
            nvi_data = json.load(f)

        if clean_data:
            before = len(nvi_data)
            nvi_data = [q for q in nvi_data if not is_corrupt_expert_answer(q.get("answer", ""))]
            for q in nvi_data:
                q["answer"] = clean_expert_answer(q["answer"])
            skipped = before - len(nvi_data)
            if skipped:
                print(f"  {domain}: skipped {skipped} corrupt expert answers")

        print(f"\n  {domain}: {len(nvi_data)} questions")

        sections = loader.load_inkoopbeleid_sections(domain)
        matcher = SectionMatcher(sections)
        supp_chunks = loader.load_supplementary_chunks()
        supp_matcher = SupplementaryMatcher(supp_chunks) if supp_chunks else None

        questions = [
            NvIQuestion(
                section=q.get("section", ""),
                question=q["question"],
                answer=q["answer"],
            )
            for q in nvi_data
        ]

        print(f"  {domain}: generating answers...")
        generator = AnswerGenerator(settings)
        answers = await generator.generate_all_answers(
            questions, matcher, supp_matcher,
            progress_callback=lambda c, t: print(f"\r  {domain}: {c}/{t}", end="", flush=True),
        )
        print()

        answer_map = {a.question: a for a in answers}

        print(f"  {domain}: judging {len(nvi_data)} answers...")
        sem = asyncio.Semaphore(20)

        async def judge_one(q):
            async with sem:
                a = answer_map.get(q["question"])
                if not a:
                    return None
                result = await judge_answer(
                    q["question"], q["answer"], a.answer, settings
                )
                return {
                    "domain": domain,
                    "section": q.get("section", ""),
                    "question": q["question"][:150],
                    "expert_answer": q["answer"][:300],
                    "generated_answer": a.answer[:300],
                    "confidence": a.confidence,
                    "score": result["score"],
                    "reasoning": result["reasoning"],
                }

        tasks = [judge_one(q) for q in nvi_data]
        judged = 0
        for coro in asyncio.as_completed(tasks):
            result = await coro
            if result:
                all_results.append(result)
            judged += 1
            if judged % 50 == 0:
                print(f"\r  {domain}: judged {judged}/{len(nvi_data)}", end="", flush=True)
        print(f"\r  {domain}: judged {len(nvi_data)}/{len(nvi_data)}")

    return {
        "timestamp": datetime.now().isoformat(),
        "commit": _get_git_hash(),
        "model": settings.model,
        "total_questions": len(all_results),
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

    by_domain = defaultdict(list)
    for r in results:
        by_domain[r["domain"]].append(r)

    print(f"\n{'='*80}")
    print(f"FULL NvI EVALUATION — {data['commit']} — {data['model']}")
    print(f"{'='*80}")

    total_score = 0
    total_max = 0
    total_by_score = defaultdict(int)

    for domain in sorted(by_domain.keys()):
        items = by_domain[domain]
        scores = [r["score"] for r in items]
        avg = sum(scores) / len(scores) if scores else 0
        score_dist = defaultdict(int)
        for s in scores:
            score_dist[s] += 1
            total_by_score[s] += 1

        domain_total = sum(scores)
        domain_max = len(scores) * 3
        total_score += domain_total
        total_max += domain_max

        pct = domain_total / domain_max * 100 if domain_max else 0
        print(f"\n  {domain}: {len(items)} questions — avg {avg:.2f}/3 ({pct:.0f}%)")
        print(f"    Score distribution: 3={score_dist[3]} 2={score_dist[2]} 1={score_dist[1]} 0={score_dist[0]}")

        # Show worst answers (score 0)
        zeros = [r for r in items if r["score"] == 0]
        if zeros:
            print(f"    Worst (score=0): {len(zeros)} questions")
            for r in zeros[:5]:
                print(f"      {r['question'][:80]}")
                print(f"        {r['reasoning'][:100]}")

    pct_total = total_score / total_max * 100 if total_max else 0
    print(f"\n{'='*80}")
    print(f"TOTAL: {len(results)} questions — {total_score}/{total_max} ({pct_total:.0f}%)")
    print(f"Score distribution: 3={total_by_score[3]} 2={total_by_score[2]} 1={total_by_score[1]} 0={total_by_score[0]}")
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

    clean_data = "--no-clean" not in args

    print(f"Model: {settings.model}")
    print(f"Clean data: {clean_data}")
    data = await run_full_eval(settings, domain_filter, clean_data=clean_data)
    print_results(data)

    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = output_dir / f"full_eval_{timestamp}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
