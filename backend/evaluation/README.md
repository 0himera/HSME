# Stage 2 Eval

Read-only quality measurement for the HSME answer pipeline (L0–L4).

## Full baseline run (answer quality)

Persists a timestamped report under `backend/evaluation/reports/{run_id}/`:

```bash
PYTHONPATH=. uv run python backend/evaluation/runners/run_e2e_eval.py
```

Optional LLM-as-judge:

```bash
PYTHONPATH=. uv run python backend/evaluation/runners/run_e2e_eval.py --llm-judge
```

## Retrieval baseline (optional)

```bash
PYTHONPATH=. uv run python backend/evaluation/runners/run_retrieval_eval.py
```

## Dry-run (L0–L3 only, no answer-quality metrics)

Does **not** produce meaningful `success_rate` — L4 judge is skipped (`answer_judging: skipped_dry_run`):

```bash
PYTHONPATH=. uv run python backend/evaluation/runners/run_e2e_eval.py --no-llm
```

## Reports policy

Only **operator-run timestamped** CLI baselines belong in `backend/evaluation/reports/`.
Pytest and dry-run artifacts write to `tmp_path` and are gitignored.

## Golden dataset (11 questions)

| Category | ids | Purpose |
|----------|-----|---------|
| `canonical` | q001–q004, q011 | Hackathon / multi-hop questions |
| `deterministic` | q005–q006 | Exact numeric facts from seed experiments |
| `easy` | q007–q008 | Broad retrieval on seed corpus |
| `off_topic` | q009–q010 | Negative cases (empty retrieval expected) |

## Stage 2b (implemented)

- **TTFT / TTFA:** Streaming in `synthesize_vsa_answer`; exposed as `llm_ttft_s` / `llm_ttfa_s` in `/api/search` and E2E reports.
- **LLM-as-judge:** `backend/evaluation/judges/llm_judge.py`; enable with `--llm-judge` on E2E runner.

## Architectural risk triage (RAP)

Score each risk: **S** (severity), **L** (likelihood), **F** (fix safety), 1–5.
**Do now** when `S×L ≥ 12` and `F ≥ 4`. See `documentation/stages.md` for the full matrix.
