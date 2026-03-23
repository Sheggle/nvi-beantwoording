# NvI-Beantwoording Autonomous Improvement Program

You are an autonomous agent improving the NvI (Nota van Inlichtingen) answering system for Zilveren Kruis healthcare procurement. You work in a loop: run evaluations, analyze results against expert feedback, find the highest-impact issue, fix it, verify the fix, and repeat.

## Context

This system automatically answers care provider questions about Wlz (long-term care) procurement policies across three domains: GGZ (mental health), GZ (disability care), VV (nursing/elderly care). Experts have scored a subset of answers on a 1-5 scale. Current mean expert score: ~1.8. The goal is to improve this.

## Setup

1. Read codebase context: `README.md`, `docs/writeup.md`
2. Ensure you're on `main` branch with a clean working tree
3. Ensure `feedback/*.xlsx` files exist (expert-scored answers)
4. Initialize `results.tsv` if it doesn't exist (tab-separated: `commit | mean_expert | n_scored | status | description`)

## What you can modify

- `src/answer_generator.py` — System prompt, improvement flags, generation logic
- `src/section_matcher.py` — How questions are matched to policy sections
- `src/supplementary_matcher.py` — How supplementary docs are matched
- `src/background_context.py` — Fixed domain knowledge injected into prompts
- `src/evaluator.py` — Post-hoc evaluation logic
- `src/config.py` — Settings, model choice, flags
- `src/data_loader.py` — Data loading logic
- `src/models.py` — Data models
- `parsed_data/extra/` — Supplementary document chunks

## What you CANNOT modify

- `feedback/*.xlsx` — Expert feedback (ground truth)
- `parsed_data/NvI-*.json` — Source questions
- `parsed_data/Inkoopbeleid-*.json` — Policy document sections
- `scripts/eval_feedback.py` — Evaluation script

## Metric

**Expert feedback score** (1-5) on the scored subset:
- **5**: Same content & conclusion as reference answer
- **4**: Same direction, minor differences
- **3**: Partial overlap
- **2**: Different approach but not contradictory
- **1**: Contradictory or completely different

Current baseline: ~1.8 mean across 39 scored questions.

## Expert feedback: identified issues

From the expert comments in the feedback files:

### Issue 1: Missing appendix/bijlage content
- "Bijlage 7 beter opnemen in de prompt"
- "Informatie over tarief en opslagen ontbreekt"
- "Dit zou uit het inkoopbeleid te halen moeten zijn. Hoofdstuk 6"
- **Root cause**: Supplementary docs (bijlage 7, 10, etc.) not being matched or included
- **Affects**: GGZ, GZ, VV

### Issue 2: Wrong section references
- "Verwijst niet naar goede sectie"
- "Model kijkt niet naar paragraaf 7"
- "Beperkt zich in het antwoord teveel tot 1 sectie"
- **Root cause**: Section matcher finds wrong sections or too few
- **Affects**: GZ, VV

### Issue 3: Too verbose / not direct enough
- "Bondiger formuleren"
- "Geeft weer onnodige info"
- **Root cause**: System prompt not strict enough on brevity
- **Affects**: VV, GZ

### Issue 4: Procedure/process questions need external docs
- "Check bij Charlotte of er document is procedure NvI"
- Multiple questions about NvI procedures can't be answered from inkoopbeleid alone
- **Root cause**: Missing source documents for procedural questions
- **Affects**: GGZ

### Issue 5: Not interpreting/inferring from policy text
- "Waarom interpreteert Model de tekst in inkoopbeleid niet goed?"
- "Staat wel in inkoopbeleid. Af te leiden uit hoofdstuk"
- **Root cause**: Model too literal, doesn't derive answers from indirect references
- **Affects**: GZ, VV

## The Loop

Run this loop forever until interrupted:

### Step 1: Run evaluation (if needed)

If the current commit doesn't have results:
```bash
cd /Users/ignacekonig/projects/nvi-beantwoording
uv run python scripts/eval_feedback.py
```
This takes ~5 minutes (39 questions × 3 domains). Results go to `output/feedback_eval_*.json`.

### Step 2: Analyze results

For each question, check:
- Expert score vs AI-generated answer quality
- Expert comments for specific actionable feedback
- Which domains/sections are weakest

Group issues by root cause (see "identified issues" above).

### Step 3: Pick highest impact cause

Choose the root cause that would improve the most questions. Prefer:
1. Issues affecting many questions across domains
2. Issues with clear actionable fixes (add missing data, fix matching)
3. Structural fixes over prompt tuning

### Step 4: Branch and fix

```bash
git checkout -b fix/<descriptive-name>
```

Common fix types:
- **Add missing supplementary content**: Parse bijlage PDFs, add chunks to `parsed_data/extra/supplementary_chunks.json`
- **Improve section matching**: Better keyword extraction, semantic matching, broader section inclusion
- **Tune system prompt**: Brevity instructions, interpretation guidance
- **Add domain knowledge**: Expand `background_context.py` with domain-specific facts
- **Enable/tune improvements**: Toggle `enable_*` flags, adjust improvement prompts

### Step 5: Test the fix

```bash
uv run python scripts/eval_feedback.py
```

### Step 6: Evaluate

Compare expert scores on feedback questions:
- The fix is **kept** if mean expert-relevant score improves (even slightly)
- The fix is **discarded** if scores decrease or no improvement

### Step 7: Record and continue

Append to `results.tsv`:
```
<commit>\t<mean_score>\t<n_scored>\t<keep|discard>\t<description>
```

If **kept**: merge to main, this is the new baseline.
If **discarded**: `git checkout main && git branch -D fix/<name>`.

### Step 8: LOOP

Go back to Step 1. Never pause, never ask for confirmation.

## Important rules

- **NEVER PAUSE**: Run autonomously until interrupted.
- **One fix per iteration**: Keep changes atomic.
- **Commit before running**: Tie results to specific commits.
- **Focus on expert-scored questions**: These 39 questions are the ground truth. Improving on them is what matters.
- **Read expert comments carefully**: They contain specific, actionable guidance.
- **Track everything**: `results.tsv` is the experiment log.
- **Time budget**: Each eval run takes ~5 min. Don't exceed 10 min.
- **Keep it simple**: A targeted prompt change that fixes 5 questions beats a large refactor.
- **Cross-domain awareness**: Fixes should ideally improve all three domains (GGZ, GZ, VV), not just one.
