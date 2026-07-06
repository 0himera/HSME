"""LLM-as-judge for E2E eval (optional Stage 2b)."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from backend.services.nlp_extractor import NLPExtractor
from backend.core.prompts import load_prompt


def _parse_judge_json(content: str) -> Dict[str, Any]:
    text = content.strip()
    json_match = re.search(r"(\{.*\})", text, re.DOTALL)
    if json_match:
        text = json_match.group(1)
    else:
        cb_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if cb_match:
            text = cb_match.group(1).strip()
    parsed = json.loads(text)
    score = float(parsed.get("score", 0))
    score = max(0.0, min(1.0, score))
    return {
        "score": round(score, 4),
        "reasoning": str(parsed.get("reasoning", "")),
        "pass": score >= 0.5,
    }


async def evaluate_answer_with_llm(
    query: str,
    answer: Optional[str],
    expected_keywords: Optional[List[str]] = None,
    *,
    timeout_s: float = 30.0,
) -> Dict[str, Any]:
    """Score answer relevance via YandexGPT. Returns score 0..1 and reasoning."""
    import asyncio

    if not answer:
        return {
            "score": 0.0,
            "pass": False,
            "reasoning": "empty answer",
        }

    keywords_hint = ""
    if expected_keywords:
        keywords_hint = f"\nОжидаемые ключевые факты/термины: {', '.join(expected_keywords)}"

    prompt_config = load_prompt("llm_judge")
    system_prompt = prompt_config["system"]
    user_prompt = prompt_config["user"].format(
        query=query,
        answer_preview=answer[:3000],
        keywords_hint=keywords_hint,
    )

    try:
        extractor = NLPExtractor()
        coro = extractor.client.chat.completions.create(
            model=extractor.model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            max_tokens=1500,
        )
        response = await asyncio.wait_for(coro, timeout=timeout_s)
        content = response.choices[0].message.content
        if not content:
            content = getattr(response.choices[0].message, "reasoning_content", None) or ""
        return _parse_judge_json(content)
    except Exception as exc:
        return {
            "score": 0.0,
            "pass": False,
            "reasoning": f"judge error: {type(exc).__name__}",
        }
