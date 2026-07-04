"""Shared utilities for eval runners."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

GOLDEN_DEFAULT = Path(__file__).resolve().parents[1] / "golden" / "questions.jsonl"
REPORTS_ROOT = Path(__file__).resolve().parents[1] / "reports"

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"api[_-]?key", re.IGNORECASE),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]+", re.IGNORECASE),
]


def load_golden_questions(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    golden_path = path or GOLDEN_DEFAULT
    if not golden_path.exists():
        raise FileNotFoundError(f"Golden dataset not found: {golden_path}")

    questions: List[Dict[str, Any]] = []
    with golden_path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                questions.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {golden_path}:{line_no}") from exc
    return questions


def create_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ensure_report_dir(run_id: str) -> Path:
    report_dir = REPORTS_ROOT / run_id
    report_dir.mkdir(parents=True, exist_ok=True)
    return report_dir


def resolve_report_dir(run_id: str, report_dir: Optional[Path] = None) -> Path:
    """Persist under repo reports/ by default; tests may override with tmp_path."""
    if report_dir is not None:
        target = Path(report_dir)
        target.mkdir(parents=True, exist_ok=True)
        return target
    return ensure_report_dir(run_id)


def redact_secrets(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_markdown_summary(path: Path, summary: Dict[str, Any]) -> None:
    meta = summary.get("run_metadata", {})
    agg = summary.get("aggregate_metrics", {})
    failures = summary.get("failed_or_skipped", [])
    artifacts = summary.get("artifact_paths", {})

    lines = [
        "# Eval Run Summary",
        "",
        "## Run metadata",
        f"- **run_id:** `{meta.get('run_id', '')}`",
        f"- **runner:** `{meta.get('runner', '')}`",
        f"- **questions_total:** {meta.get('questions_total', 0)}",
        f"- **questions_evaluated:** {meta.get('questions_evaluated', 0)}",
        f"- **questions_skipped:** {meta.get('questions_skipped', 0)}",
        f"- **errors:** {meta.get('errors', 0)}",
        "",
        "## Aggregate metrics",
    ]
    for key, value in sorted(agg.items()):
        if isinstance(value, float):
            lines.append(f"- **{key}:** {value:.4f}")
        else:
            lines.append(f"- **{key}:** {value}")

    lines.extend(["", "## Failed / skipped cases"])
    if failures:
        for item in failures:
            lines.append(
                f"- `{item.get('id', '?')}` — {item.get('status', 'unknown')}: "
                f"{item.get('reason', '')}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Artifact paths"])
    for key, value in sorted(artifacts.items()):
        lines.append(f"- **{key}:** `{value}`")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def finalize_summary(
    *,
    runner: str,
    run_id: str,
    report_dir: Path,
    questions: List[Dict[str, Any]],
    per_question: List[Dict[str, Any]],
    aggregate_metrics: Dict[str, Any],
    run_metadata_extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    skipped = [q for q in per_question if q.get("retrieval_skipped") or q.get("status") == "skipped"]
    errors = [q for q in per_question if q.get("error") or q.get("status") == "error"]
    evaluated = [q for q in per_question if q.get("status") not in ("skipped", "error")]

    failed_or_skipped = []
    for q in per_question:
        if q.get("retrieval_skipped"):
            failed_or_skipped.append(
                {
                    "id": q.get("id"),
                    "status": "retrieval_skipped",
                    "reason": q.get("skip_reason", "no expected_experiment_ids"),
                }
            )
        elif q.get("error"):
            failed_or_skipped.append(
                {
                    "id": q.get("id"),
                    "status": "error",
                    "reason": redact_secrets(str(q.get("error"))),
                }
            )
        elif q.get("judge_pass") is False:
            failed_or_skipped.append(
                {
                    "id": q.get("id"),
                    "status": "judge_fail",
                    "reason": q.get("judge_details", "rule judge failed"),
                }
            )

    run_metadata: Dict[str, Any] = {
        "run_id": run_id,
        "runner": runner,
        "questions_total": len(questions),
        "questions_evaluated": len(evaluated),
        "questions_skipped": len(skipped),
        "errors": len(errors),
    }
    if run_metadata_extra:
        run_metadata.update(run_metadata_extra)

    summary = {
        "run_metadata": run_metadata,
        "aggregate_metrics": aggregate_metrics,
        "per_question": per_question,
        "failed_or_skipped": failed_or_skipped,
        "artifact_paths": {
            "report_dir": str(report_dir),
            "summary_json": str(report_dir / "summary.json"),
            "summary_md": str(report_dir / "summary.md"),
        },
    }

    write_json(report_dir / "summary.json", summary)
    write_markdown_summary(report_dir / "summary.md", summary)
    return summary
