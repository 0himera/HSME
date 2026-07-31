"""Yandex Cloud text embedding client (text-search-query smoke + Stage 10 helper)."""

from __future__ import annotations

import argparse
import math
import sys
from typing import Any

import httpx

from backend.services.yandex_aistudio_client import (
    YandexAIStudioAPIError,
    YandexAIStudioConfig,
    resolve_yandex_config,
)

DEFAULT_EMBEDDING_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/textEmbedding"
DEFAULT_QUERY_MODEL = "text-search-query/latest"


class YandexEmbeddingClient:
    def __init__(
        self,
        config: YandexAIStudioConfig,
        *,
        model_slug: str = DEFAULT_QUERY_MODEL,
        embedding_url: str = DEFAULT_EMBEDDING_URL,
        timeout_s: float = 30.0,
    ) -> None:
        self.config = config
        self.model_slug = model_slug
        self.embedding_url = embedding_url
        self.timeout_s = timeout_s

    @property
    def model_uri(self) -> str:
        return f"emb://{self.config.folder_id}/{self.model_slug}"

    async def embed_async(self, text: str) -> list[float]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Api-Key {self.config.api_key}",
        }
        body = {
            "modelUri": self.model_uri,
            "text": text.strip(),
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(self.embedding_url, json=body, headers=headers)
                response.raise_for_status()
                payload: dict[str, Any] = response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500] if exc.response is not None else str(exc)
            raise YandexAIStudioAPIError(
                f"Embedding request failed ({exc.response.status_code}): {detail}",
                status_code=exc.response.status_code if exc.response is not None else None,
            ) from exc
        except httpx.RequestError as exc:
            raise YandexAIStudioAPIError(f"Embedding network error: {exc}") from exc

        embedding = payload.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            raise YandexAIStudioAPIError(
                f"Embedding response missing non-empty 'embedding' field: {payload!r:.200}"
            )
        return [float(value) for value in embedding]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError(f"Vector dimensions differ: {len(left)} vs {len(right)}")
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


async def run_smoke(
    *,
    text_ru: str = "никель",
    text_en: str = "nickel",
    unrelated: str = "кучное выщелачивание",
    env_file: str | None = None,
) -> dict[str, Any]:
    config = resolve_yandex_config(env_file=env_file)
    client = YandexEmbeddingClient(config)

    emb_ru = await client.embed_async(text_ru)
    emb_en = await client.embed_async(text_en)
    emb_unrelated = await client.embed_async(unrelated)

    sim_ru_en = cosine_similarity(emb_ru, emb_en)
    sim_ru_unrelated = cosine_similarity(emb_ru, emb_unrelated)

    return {
        "model_uri": client.model_uri,
        "folder_id": config.folder_id,
        "vector_dim": len(emb_ru),
        "samples": {
            text_ru: emb_ru[:5],
            text_en: emb_en[:5],
            unrelated: emb_unrelated[:5],
        },
        "similarity": {
            f"{text_ru} vs {text_en}": sim_ru_en,
            f"{text_ru} vs {unrelated}": sim_ru_unrelated,
        },
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke-test Yandex text-search-query embeddings using .env creds.",
    )
    parser.add_argument("--env-file", default=".env", help="Path to dotenv file (default: .env)")
    parser.add_argument("--text-ru", default="никель", help="Russian sample term")
    parser.add_argument("--text-en", default="nickel", help="English sample term")
    parser.add_argument(
        "--unrelated",
        default="кучное выщелачивание",
        help="Unrelated control term for similarity check",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    import asyncio

    args = _build_parser().parse_args(argv)
    try:
        result = asyncio.run(
            run_smoke(
                text_ru=args.text_ru,
                text_en=args.text_en,
                unrelated=args.unrelated,
                env_file=args.env_file,
            )
        )
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    print("OK: Yandex Search Query Embedding")
    print(f"model_uri: {result['model_uri']}")
    print(f"folder_id: {result['folder_id']}")
    print(f"vector_dim: {result['vector_dim']}")
    for label, preview in result["samples"].items():
        print(f"sample[{label!r}] first5: {preview}")
    for label, value in result["similarity"].items():
        print(f"cosine[{label}]: {value:.4f}")

    if result["similarity"][f"{args.text_ru} vs {args.text_en}"] <= result["similarity"][f"{args.text_ru} vs {args.unrelated}"]:
        print(
            "WARN: bilingual pair is not more similar than unrelated control; "
            "check model access or term choice.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
