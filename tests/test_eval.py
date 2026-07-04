"""Tests for Stage 2 eval runners."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Isolated DB for eval tests
os.environ["HSME_DATABASE_FILE"] = "test_eval_db_state.pkl"
_eval_db = Path("test_eval_db_state.pkl")
if _eval_db.exists():
    _eval_db.unlink()

from backend.evaluation.judges.llm_judge import _parse_judge_json, evaluate_answer_with_llm
from backend.evaluation.judges.rule_judge import evaluate_answer
from backend.evaluation.metrics import (
    mean_reciprocal_rank,
    precision_at_k,
    recall,
    recall_at_k,
)
from backend.evaluation.runners.common import (
    load_golden_questions,
    redact_secrets,
)
from backend.evaluation.runners.query_parse import parse_query_local_sync
from backend.evaluation.runners.run_e2e_eval import run_e2e_eval
from backend.evaluation.runners.run_retrieval_eval import run_retrieval_eval

GOLDEN_PATH = Path(__file__).resolve().parents[1] / "backend" / "evaluation" / "golden" / "questions.jsonl"


@pytest.fixture
def eval_reports_root(tmp_path):
    return tmp_path / "reports"


def test_retrieval_metrics_pure():
    retrieved = ["EXP-NI-01", "EXP-CU-01", "EXP-HL-01"]
    relevant = {"EXP-NI-01", "EXP-NI-02", "EXP-NI-03"}
    assert precision_at_k(retrieved, relevant, 3) == pytest.approx(1 / 3)
    assert recall_at_k(retrieved, relevant, 3) == pytest.approx(1 / 3)
    assert mean_reciprocal_rank(retrieved, relevant) == 1.0
    assert recall([], relevant) == 0.0


def test_rule_judge_keywords():
    question = {
        "success_criteria": {"required_keywords_in_answer": ["электроэкстракция", "никель"]},
    }
    ok = evaluate_answer("Ответ про электроэкстрацию никеля в хлоридном электролите.", question)
    assert ok["pass"] is True, ok
    fail = evaluate_answer("Нет релевантных данных.", question)
    assert fail["pass"] is False


def test_rule_judge_off_topic_empty_retrieval():
    question = {
        "success_criteria": {
            "required_keywords_in_answer": ["нет релевантных"],
            "expect_empty_retrieval": True,
        },
    }
    ok = evaluate_answer(
        "Нет релевантных экспериментов для анализа.",
        question,
        retrieved_ids=[],
    )
    assert ok["pass"] is True
    fail = evaluate_answer(
        "Нет релевантных экспериментов для анализа.",
        question,
        retrieved_ids=["EXP-NI-01"],
    )
    assert fail["pass"] is False


def test_load_golden_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_golden_questions(tmp_path / "missing.jsonl")


def test_golden_dataset_has_11_questions():
    questions = load_golden_questions(GOLDEN_PATH)
    assert len(questions) == 11
    categories = {q.get("question_category") for q in questions}
    assert "deterministic" in categories
    assert "easy" in categories
    assert "off_topic" in categories


def test_deterministic_question_parsing():
    q005 = (
        "Какая светлость поверхности никелевого катода достигается при электроэкстракции "
        "в хлоридном электролите при pH 1.0 и плотности тока 300 А/м2?"
    )
    entities = parse_query_local_sync(q005)
    types = {e.type for e in entities}
    assert "Material" in types or "Process" in types
    assert any("PH" in e.value.upper() for e in entities if e.type == "Property")


def test_off_topic_parsing_empty_entities():
    entities = parse_query_local_sync("Как приготовить пиццу Маргарита в домашних условиях?")
    assert entities == []


def test_retrieval_runner_happy_path(eval_reports_root):
    run_id = "test-retrieval-run"
    summary = run_retrieval_eval(
        golden_path=GOLDEN_PATH,
        run_id=run_id,
        report_dir=eval_reports_root / run_id,
    )
    actual_dir = Path(summary["artifact_paths"]["report_dir"])
    assert actual_dir.exists()
    assert summary["aggregate_metrics"]["retrieval_evaluated"] == 6
    assert "precision_at_5" in summary["aggregate_metrics"]
    q001 = next(q for q in summary["per_question"] if q["id"] == "q001")
    assert q001["retrieval_skipped"] is True
    q002 = next(q for q in summary["per_question"] if q["id"] == "q002")
    assert q002["status"] == "ok"
    assert "EXP-NI-01" in q002["retrieved_ids"]
    q005 = next(q for q in summary["per_question"] if q["id"] == "q005")
    assert "EXP-NI-02" in q005["retrieved_ids"]
    skipped = [q for q in summary["per_question"] if q.get("retrieval_skipped")]
    assert len(skipped) == 5


def test_e2e_runner_no_llm(eval_reports_root):
    summary = run_e2e_eval(
        golden_path=GOLDEN_PATH,
        run_id="test-e2e-dry",
        report_dir=eval_reports_root / "test-e2e-dry",
        use_llm=False,
    )
    assert summary["run_metadata"]["questions_total"] == 11
    assert summary["run_metadata"]["use_llm"] is False
    assert summary["aggregate_metrics"].get("answer_judging") == "skipped_dry_run"
    assert "success_rate" not in summary["aggregate_metrics"]
    q002 = next(q for q in summary["per_question"] if q["id"] == "q002")
    assert q002.get("snapshot_paths")
    assert Path(q002["snapshot_paths"]["L0"]).exists()
    q009 = next(q for q in summary["per_question"] if q["id"] == "q009")
    assert q009["retrieved_ids"] == []
    assert q009["judge_pass"] is None


def test_e2e_llm_timeout_continues_run(eval_reports_root):
    async def slow_synth(*_args, **_kwargs):
        await asyncio.sleep(60)
        return "never", None, None

    with patch(
        "backend.evaluation.runners.run_e2e_eval.synthesize_vsa_answer",
        new=AsyncMock(side_effect=slow_synth),
    ):
        summary = run_e2e_eval(
            golden_path=GOLDEN_PATH,
            run_id="test-e2e-timeout",
            report_dir=eval_reports_root / "test-e2e-timeout",
            use_llm=True,
            llm_timeout_s=0.01,
        )

    assert summary["run_metadata"]["questions_total"] == 11
    errors = [q for q in summary["per_question"] if q.get("error") == "LLM Timeout"]
    assert len(errors) >= 1


def test_e2e_ttft_metrics_from_mock(eval_reports_root):
    async def fast_synth(*_args, **_kwargs):
        return "Ответ с электроэкстракцией никеля.", 0.1205, 0.4500

    with patch(
        "backend.evaluation.runners.run_e2e_eval.synthesize_vsa_answer",
        new=AsyncMock(side_effect=fast_synth),
    ):
        summary = run_e2e_eval(
            golden_path=GOLDEN_PATH,
            run_id="test-e2e-ttft",
            report_dir=eval_reports_root / "test-e2e-ttft",
            use_llm=True,
        )

    with_ttft = [q for q in summary["per_question"] if q.get("llm_ttft_s") is not None]
    assert len(with_ttft) >= 1
    assert summary["aggregate_metrics"].get("mean_ttft_s") is not None
    assert summary["aggregate_metrics"].get("mean_ttfa_s") is not None


def test_llm_judge_parse_json():
    result = _parse_judge_json('{"score": 0.85, "reasoning": "Contains expected facts"}')
    assert result["score"] == 0.85
    assert result["pass"] is True


@pytest.mark.asyncio
async def test_llm_judge_mock_call():
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = (
        '{"score": 0.75, "reasoning": "Partially relevant"}'
    )

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    mock_extractor = MagicMock()
    mock_extractor.client = mock_client

    with patch("backend.evaluation.judges.llm_judge.NLPExtractor", return_value=mock_extractor):
        result = await evaluate_answer_with_llm(
            "электроэкстракция никеля",
            "Ответ про электроэкстракцию.",
            ["никель"],
        )

    assert result["score"] == 0.75
    assert result["pass"] is True


def test_secrets_redacted_in_summary():
    payload = {"error": "Bearer sk-abcdefghijklmnopqrstuvwxyz1234567890"}
    redacted = redact_secrets(json.dumps(payload))
    assert "sk-" not in redacted
    assert "[REDACTED]" in redacted or "Bearer" not in redacted
