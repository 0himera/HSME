"""Retrieval metric helpers for eval runners."""

from __future__ import annotations

from typing import Iterable, List, Sequence


def _top_k(ids: Sequence[str], k: int) -> List[str]:
    return list(ids[:k])


def precision(retrieved: Sequence[str], relevant: set[str]) -> float:
    if not retrieved:
        return 0.0
    tp = sum(1 for rid in retrieved if rid in relevant)
    return tp / len(retrieved)


def recall(retrieved: Sequence[str], relevant: set[str]) -> float:
    if not relevant:
        return 0.0
    tp = sum(1 for rid in retrieved if rid in relevant)
    return tp / len(relevant)


def precision_at_k(retrieved: Sequence[str], relevant: set[str], k: int) -> float:
    return precision(_top_k(retrieved, k), relevant)


def recall_at_k(retrieved: Sequence[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    top = set(_top_k(retrieved, k))
    tp = len(top & relevant)
    return tp / len(relevant)


def mean_reciprocal_rank(retrieved: Sequence[str], relevant: set[str]) -> float:
    for rank, rid in enumerate(retrieved, start=1):
        if rid in relevant:
            return 1.0 / rank
    return 0.0


def aggregate_metric(values: Iterable[float]) -> float:
    vals = list(values)
    if not vals:
        return 0.0
    return sum(vals) / len(vals)
