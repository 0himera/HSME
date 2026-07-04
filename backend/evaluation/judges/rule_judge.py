"""Rule-based answer judge for E2E eval."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _normalize(text: str) -> str:
    return text.lower().strip()


def _keyword_match(norm_answer: str, keyword: str) -> bool:
    norm_kw = _normalize(keyword)
    if norm_kw in norm_answer:
        return True
    min_stem = max(5, len(norm_kw) - 5)
    for stem_len in range(len(norm_kw), min_stem - 1, -1):
        if norm_kw[:stem_len] in norm_answer:
            return True
    return False


def _keyword_hits(answer: str, keywords: List[str]) -> Dict[str, bool]:
    norm = _normalize(answer)
    return {kw: _keyword_match(norm, kw) for kw in keywords}


def evaluate_answer(
    answer: Optional[str],
    question: Dict[str, Any],
    *,
    retrieved_ids: Optional[List[str]] = None,
    recall_at_5: Optional[float] = None,
) -> Dict[str, Any]:
    """Return pass/fail and score based on success_criteria."""
    criteria = question.get("success_criteria") or {}
    required_keywords: List[str] = criteria.get("required_keywords_in_answer") or []
    min_recall = criteria.get("min_recall_at_5")
    expect_empty = criteria.get("expect_empty_retrieval", False)

    if not answer:
        return {
            "pass": False,
            "score": 0.0,
            "details": "empty answer",
            "keyword_hits": {},
        }

    hits = _keyword_hits(answer, required_keywords) if required_keywords else {}
    keyword_ok = all(hits.values()) if required_keywords else True

    recall_ok = True
    if min_recall is not None and recall_at_5 is not None:
        recall_ok = recall_at_5 >= float(min_recall)

    empty_ok = True
    if expect_empty and retrieved_ids is not None:
        empty_ok = len(retrieved_ids) == 0

    passed = keyword_ok and recall_ok and empty_ok
    score_parts = []
    if required_keywords:
        score_parts.append(sum(1 for v in hits.values() if v) / len(required_keywords))
    if min_recall is not None and recall_at_5 is not None:
        score_parts.append(min(1.0, recall_at_5 / float(min_recall)) if min_recall > 0 else 1.0)
    if expect_empty:
        score_parts.append(1.0 if empty_ok else 0.0)
    score = sum(score_parts) / len(score_parts) if score_parts else (1.0 if passed else 0.0)

    details_parts = []
    if required_keywords and not keyword_ok:
        missing = [k for k, v in hits.items() if not v]
        details_parts.append(f"missing keywords: {missing}")
    if not recall_ok:
        details_parts.append(f"recall@5 {recall_at_5} < {min_recall}")
    if not empty_ok:
        details_parts.append(f"expected empty retrieval, got {retrieved_ids}")

    return {
        "pass": passed,
        "score": round(score, 4),
        "details": "; ".join(details_parts) if details_parts else "ok",
        "keyword_hits": hits,
        "retrieved_ids": retrieved_ids or [],
    }
