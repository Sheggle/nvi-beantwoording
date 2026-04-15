# NvI-Beantwoording Autonomous Improvement Program

You are an autonomous agent improving the NvI (Nota van Inlichtingen) answering system for Zilveren Kruis healthcare procurement. You work in a loop: run evaluations against a golden set, analyze failures, find the highest-impact issue, fix it, verify, and repeat.

## Context

This system automatically answers care provider questions about Wlz (long-term care) procurement policies across three domains: GGZ (mental health), GZ (disability care), VV (nursing/elderly care).

## Golden set

`golden_set.json` contains 20 expert-verified questions with:
- **golden_answer**: The correct answer (in Dutch)
- **key_assertions**: Verifiable checks that any correct answer must satisfy (e.g., "must reference bijlage 7", "must say nee")
- **source_sections**: Which policy sections contain the answer

The golden set is the ground truth. The metric is **assertions passed** — each question has 3-5 assertions, totaling ~75 assertions.

### Golden set maintenance

If the system produces an answer that **differs from the golden answer but is factually correct**, update the golden set:
1. Read the relevant policy sections to verify
2. If the system's answer is better or equally correct, update `golden_answer` and/or `key_assertions`
3. Commit the golden set update separately with clear reasoning

This prevents the golden set from becoming stale or blocking valid improvements.

## Setup

1. Read codebase context: `README.md`, `src/answer_generator.py`, `src/section_matcher.py`
2. Ensure you're on `main` branch with clean working tree
3. Run baseline if no results exist: `uv run python scripts/eval_golden.py`
4. Initialize `results.tsv` if empty

## What you can modify

- `src/answer_generator.py` — System prompt, improvement flags, generation logic
- `src/section_matcher.py` — How questions are matched to policy sections
- `src/supplementary_matcher.py` — How supplementary docs are matched
- `src/background_context.py` — Fixed domain knowledge injected into prompts
- `src/evaluator.py` — Post-hoc evaluation logic
- `src/config.py` — Settings, model choice, flags
- `src/data_loader.py` — Data loading logic
- `src/models.py` — Data models
- `parsed_data/extra/` — Supplementary document chunks (add more reference material)
- `golden_set.json` — Update if system produces a verifiably better answer

## What you CANNOT modify

- `scripts/eval_golden.py` — The evaluation script
- `parsed_data/NvI-*.json` — Source questions
- `parsed_data/Inkoopbeleid-*.json` — Policy document sections
- `feedback/*.xlsx` — Original expert feedback

## Identified issues (from expert feedback)

### Issue 1: Missing appendix/bijlage content (HIGH IMPACT)
- "Bijlage 7 beter opnemen in de prompt" — tariff methodology
- "Informatie over tarief en opslagen ontbreekt"
- **Root cause**: Supplementary docs (bijlage 7, 10) not matched or included
- **Affected questions**: Q9 (bijlage 7, 75% norm), Q5 (voorschrift zorgtoewijzing), Q13 (NZa beleidsregels)
- **Fix ideas**: Parse bijlage PDFs into supplementary_chunks.json, improve supplementary matching

### Issue 2: Wrong section references / too narrow matching (HIGH IMPACT)
- "Verwijst niet naar goede sectie", "Model kijkt niet naar paragraaf 7"
- "Beperkt zich teveel tot 1 sectie"
- **Root cause**: Section matcher finds wrong sections or too few
- **Affected questions**: Q18 (should reference 6.18), Q6 (wrong interpretation), Q17 (missing passage)
- **Fix ideas**: Broaden keyword matching, include parent+child sections, semantic similarity

### Issue 3: Not decisive enough / too verbose
- "Bondiger formuleren", "Geeft onnodige info"
- "Gewoon nee teruggeven als iets niet te vinden is"
- **Root cause**: System prompt too cautious, model hedges instead of answering directly
- **Affected questions**: Q3, Q10, Q17, Q19
- **Fix ideas**: Stricter prompt on brevity and directness, "if information is clearly stated, answer directly"

### Issue 4: Doesn't interpret/infer from policy text
- "Waarom interpreteert Model de tekst niet goed?"
- "Af te leiden uit hoofdstuk" — answer is derivable but model doesn't connect the dots
- **Root cause**: Model too literal, doesn't synthesize across sections
- **Affected questions**: Q2, Q6 (jargon "domeinen" misunderstood), Q14
- **Fix ideas**: Add domain glossary to background_context.py, teach jargon

### Issue 5: Procedural questions lacking source docs
- "Check Charlotte op procedures" — NvI process info not in inkoopbeleid
- **Affected questions**: Q8, Q10, Q12, Q15, Q16
- **Fix ideas**: Add procedural knowledge to background_context.py (NvI process, verlenging, voorschrift zorgtoewijzing timelines)

## The Loop

### Step 1: Run evaluation

```bash
cd /Users/ignacekonig/projects/nvi-beantwoording
uv run python scripts/eval_golden.py
```

Takes ~3-5 minutes (20 questions, ~75 assertion checks). Output: assertions passed/total per question.

### Step 2: Analyze failures

For each failed assertion:
- What did the system answer vs what was expected?
- Is this a retrieval problem (wrong sections matched), a generation problem (right context but bad answer), or a knowledge gap (info not available)?
- Check if the golden answer should be updated (system might be right)

### Step 3: Group and prioritize

Group failures by root cause (see identified issues above). Pick the cause that fixes the most assertions. Prefer:
1. Retrieval fixes (section matching, supplementary docs) — most reliable
2. Knowledge additions (background_context, supplementary chunks) — deterministic
3. Prompt tuning — less predictable but can address interpretation issues

### Step 4: Branch and fix

```bash
git checkout -b fix/<descriptive-name>
```

### Step 5: Test

```bash
uv run python scripts/eval_golden.py
```

### Step 6: Evaluate

- **Keep** if more assertions pass than before, with no regressions on previously passing assertions
- **Discard** if assertions decrease or regressions appear
- **Update golden set** if system produces a verifiably better answer

### Step 7: Record

Append to `results.tsv`:
```
<commit>\t<assertions_passed>\t<assertions_total>\t<status>\t<description>
```

### Step 8: LOOP

Merge if kept, discard if not. Go to Step 1. Never pause.

## Important rules

- **NEVER PAUSE**: Run autonomously until interrupted.
- **One fix per iteration**: Keep changes atomic and isolatable.
- **Commit before running**: Results must be tied to a commit.
- **Verify golden set**: If system answer differs but is correct per policy text, update golden_set.json.
- **Read the policy text**: Before writing fixes, read the actual Inkoopbeleid sections. Don't guess.
- **Cross-domain**: Fixes should work across GGZ, GZ, VV — the matching and generation logic is shared.
- **Track everything**: `results.tsv` is the experiment log.
- **Keep it simple**: A targeted fix that passes 5 more assertions beats a large refactor.
