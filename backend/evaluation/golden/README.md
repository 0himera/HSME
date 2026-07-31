# Golden dataset (Stage 2 Eval)

Read-only eval questions derived from the hackathon competition brief.

## Schema (v1)

Each line in `questions.jsonl` is one JSON object:

| Field | Required | Description |
|-------|----------|-------------|
| `id` | yes | Stable question id (`q001` …) |
| `query` | yes | Canonical NL question from hackathon task |
| `coverage_status` | yes | `supported` \| `e2e_only` \| `coverage_gap` |
| `eval_mode` | yes | `full` \| `e2e_only` \| `baseline_only` |
| `expected_experiment_ids` | no | Relevant experiment ids for L1–L2 retrieval metrics |
| `expected_evidence_keywords` | no | Keywords expected in evidence or answer |
| `geography` | no | Optional filter (`RU`, `Global`, `null`) |
| `question_category` | no | `canonical` \| `deterministic` \| `easy` \| `off_topic` |
| `success_criteria` | no | Rule-judge thresholds |

### `success_criteria` (optional)

```json
{
  "min_recall_at_5": 0.5,
  "required_keywords_in_answer": ["электроэкстракция"]
}
```

## Coverage matrix

See [coverage_matrix.json](./coverage_matrix.json) for the pre-flight check against current seed corpus (`backend/repository/seeding.py`).

| id | Topic | coverage_status | eval_mode |
|----|-------|-----------------|-----------|
| q001 | Обессоливание воды | `coverage_gap` | `e2e_only` |
| q002 | Циркуляция католита / электроэкстракция Ni | `supported` | `full` |
| q003 | Au/Ag/МПГ штейн–шлак | `coverage_gap` | `e2e_only` |
| q004 | Закачка шахтных вод | `coverage_gap` | `e2e_only` |
| q005 | Светлость катода Ni (pH 1.0) | `supported` | `full` |
| q006 | Извлечение Ni при 5°C HL | `supported` | `full` |
| q007 | Медная EW Long Harbour | `supported` | `full` |
| q008 | Кучное выщелачивание | `supported` | `full` |
| q009 | Пицца (off-topic) | `supported` | `e2e_only` |
| q010 | Погода (off-topic) | `supported` | `e2e_only` |

**Note:** q002 is `supported` for nickel electrowinning retrieval (`EXP-NI-*`) but the corpus does not yet contain catholyte flow-rate data; keywords judge checks electrowinning/nickel only.

## Corpus vs golden alignment policy

Golden `expected_experiment_ids` target the **seed / demo experiments** (`EXP-NI-*`, `EXP-HL-*`, `EXP-CU-*` from `backend/repository/seeding.py`), not the full production corpus density (ОИП-*, Австралия-*, etc.).

| Strategy | When to use |
|----------|-------------|
| Keep seed expected IDs (default) | Regression against known seed facts; Stage 9.1+ retrieval/E2E |
| Eval / demo on seed snapshot | Isolate recall from full-corpus density drowning |
| Update expected IDs to full-corpus winners | Only after explicit product decision that ОИП/peer hits are acceptable gold |
| Full wipe + re-ingest | **Only after** a corpus quality audit finds truly broken records (dupes, empty entities, corrupt RAW). Density alone is not corruption |

Do **not** start with blind re-ingest to “fix” recall drops: first attribute failures via E2E snapshots (`L0` → `L1_pre_rerank` → `L1` with separate `vsa_score` / `hybrid_score`) to L0, VSA, rerank, or L4.

Off-topic questions (q009/q010) expect **empty** retrieval via the general No-Evidence gate — not category-specific logic and not a corpus wipe.

## Launch

```bash
PYTHONPATH=. uv run python backend/evaluation/runners/run_retrieval_eval.py
PYTHONPATH=. uv run python backend/evaluation/runners/run_e2e_eval.py
```
