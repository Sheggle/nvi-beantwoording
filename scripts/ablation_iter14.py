"""Ablation study for iteration 14 interventions.

Runs 5 evaluations:
  1. all_on         — all 4 new flags enabled (baseline for this iteration)
  2. no_nza         — disable enable_nza_role_emphasis
  3. no_vv_fs       — disable enable_vv_few_shot
  4. no_sections    — disable enable_section_citations
  5. no_collab      — disable enable_collaborative_framing

Usage:
    uv run python scripts/ablation_iter14.py
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.eval_golden import run_golden_eval, print_results
from src.config import Settings

ABLATION_CONFIGS = {
    "all_on": {},
    "no_nza": {"enable_nza_role_emphasis": False},
    "no_vv_fs": {"enable_vv_few_shot": False},
    "no_sections": {"enable_section_citations": False},
    "no_collab": {"enable_collaborative_framing": False},
}


async def main():
    results = {}
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    for name, overrides in ABLATION_CONFIGS.items():
        print(f"\n{'='*80}")
        print(f"  ABLATION RUN: {name}")
        if overrides:
            print(f"  Disabled: {list(overrides.keys())}")
        else:
            print(f"  All iteration-14 flags ON")
        print(f"{'='*80}")

        settings = Settings(**overrides)
        data = await run_golden_eval(settings)
        print_results(data)

        data["ablation_name"] = name
        data["ablation_overrides"] = overrides
        results[name] = data

        # Save individual run
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = output_dir / f"ablation_{name}_{timestamp}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # Print summary table
    print(f"\n\n{'='*80}")
    print("ABLATION SUMMARY")
    print(f"{'='*80}")
    print(f"{'Config':<20} {'Total':>8} {'GGZ':>8} {'GZ':>8} {'VV':>8}")
    print(f"{'-'*20} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")

    for name, data in results.items():
        total = f"{data['total_assertions_passed']}/{data['total_assertions']}"
        by_domain = {}
        for r in data["results"]:
            d = r["domain"]
            by_domain.setdefault(d, {"p": 0, "t": 0})
            by_domain[d]["p"] += r["assertions_passed"]
            by_domain[d]["t"] += r["assertions_total"]

        ggz = by_domain.get("GGZ", {"p": 0, "t": 0})
        gz = by_domain.get("GZ", {"p": 0, "t": 0})
        vv = by_domain.get("VV", {"p": 0, "t": 0})

        print(
            f"{name:<20} {total:>8} "
            f"{ggz['p']}/{ggz['t']:>3} "
            f"{gz['p']}/{gz['t']:>3} "
            f"{vv['p']}/{vv['t']:>3}"
        )

    # Also compute deltas from all_on
    if "all_on" in results:
        baseline = results["all_on"]["total_assertions_passed"]
        print(f"\nDeltas from all_on ({baseline}/{results['all_on']['total_assertions']}):")
        for name, data in results.items():
            if name == "all_on":
                continue
            delta = data["total_assertions_passed"] - baseline
            sign = "+" if delta > 0 else ""
            print(f"  {name:<20} {sign}{delta}")

    # Save summary
    summary_path = output_dir / f"ablation_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    summary = {
        name: {
            "total_passed": d["total_assertions_passed"],
            "total": d["total_assertions"],
            "overrides": d.get("ablation_overrides", {}),
        }
        for name, d in results.items()
    }
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSummary saved to {summary_path}")


if __name__ == "__main__":
    asyncio.run(main())
