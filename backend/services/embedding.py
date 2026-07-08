"""Dense embeddings and bipolar VSA projection for semantic entity vectors."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import pickle
import re
from typing import Dict, List, Optional

import numpy as np
from openai import AsyncOpenAI

from backend.core.config import YANDEX_API_KEY, YANDEX_FOLDER_ID, resolve_llm_settings
from backend.services.yandex_aistudio_client import resolve_yandex_config
from backend.services.yandex_embedding import YandexEmbeddingClient

logger = logging.getLogger(__name__)

DEFAULT_CACHE_FILE = os.environ.get("HSME_EMBEDDINGS_CACHE_FILE", ".local/embeddings_cache.pkl")
DEFAULT_TRIGRAM_DIM = 384
PROJECTION_SEED = 12345

_META_PREFIXES_PRESERVE_VALUE = frozenset({"Role", "RelationType"})


def normalize_entity_value(value: str) -> str:
    """Normalize entity value: lowercase, strip, collapse all whitespace to single space."""
    cleaned = value.strip().lower()
    return re.sub(r"\s+", " ", cleaned)


def normalize_entity_key(key: str) -> str:
    """Normalize a codebook key while preserving meta-prefix casing (Role, RelationType, NumericBase)."""
    if ":" not in key:
        return key.strip()

    prefix, value = key.split(":", 1)
    if prefix in _META_PREFIXES_PRESERVE_VALUE:
        return f"{prefix}:{value.strip()}"

    if prefix == "NumericBase":
        parts = value.rsplit(":", 1)
        if len(parts) == 2 and parts[1] in {"min", "max"}:
            return f"{prefix}:{normalize_entity_value(parts[0])}:{parts[1]}"
        return f"{prefix}:{normalize_entity_value(value)}"

    return f"{prefix}:{normalize_entity_value(value)}"


class BipolarProjection:
    """Projects dense embeddings into fixed-dimension bipolar VSA vectors."""

    def __init__(self, vsa_dim: int = 10000, seed: int = PROJECTION_SEED) -> None:
        self.vsa_dim = vsa_dim
        self.seed = seed
        self.matrices: Dict[int, np.ndarray] = {}

    def get_matrix(self, dense_dim: int) -> np.ndarray:
        if dense_dim not in self.matrices:
            rng = np.random.default_rng(self.seed + dense_dim)
            self.matrices[dense_dim] = rng.normal(
                0.0, 1.0, size=(self.vsa_dim, dense_dim)
            ).astype(np.float32)
        return self.matrices[dense_dim]

    def project(self, dense_vector: List[float]) -> np.ndarray:
        vec = np.array(dense_vector, dtype=np.float32)
        if vec.size == 0:
            vec = np.zeros(DEFAULT_TRIGRAM_DIM, dtype=np.float32)
        matrix = self.get_matrix(len(vec))
        projected = np.dot(matrix, vec)
        bipolar = np.sign(projected).astype(np.int8)
        bipolar[bipolar == 0] = 1
        return bipolar


def is_semantic_entity_key(key: str) -> bool:
    """Return True when key represents a typed entity filler (not meta VSA symbol)."""
    if ":" not in key:
        return False
    prefix = key.split(":", 1)[0]
    return prefix not in {"Role", "RelationType", "NumericBase"}


class EmbeddingService:
    """RAM/disk cached embeddings with Yandex, OpenAI, and trigram fallback."""

    def __init__(
        self,
        *,
        cache_file: str = DEFAULT_CACHE_FILE,
        trigram_dim: int = DEFAULT_TRIGRAM_DIM,
        env_file: str | None = None,
    ) -> None:
        self.cache_file = cache_file
        self.trigram_dim = trigram_dim
        self.env_file = env_file
        self.cache: Dict[str, List[float]] = {}
        self._yandex_client: YandexEmbeddingClient | None = None
        self.load_cache()

        settings = resolve_llm_settings(env_file=env_file) if env_file else resolve_llm_settings()
        self.api_key = settings.get("LLM_API_KEY")
        self.base_url = settings.get("LLM_BASE_URL")
        self.folder_id = settings.get("LLM_FOLDER_ID") or YANDEX_FOLDER_ID
        self.client = (
            AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
            if self.api_key and self.base_url
            else None
        )

    def load_cache(self) -> None:
        if not os.path.exists(self.cache_file):
            return
        try:
            with open(self.cache_file, "rb") as handle:
                loaded = pickle.load(handle)
            if isinstance(loaded, dict):
                self.cache = loaded
        except Exception as exc:
            logger.warning("Failed to load embeddings cache %s: %s", self.cache_file, exc)

    def save_cache(self) -> None:
        try:
            directory = os.path.dirname(self.cache_file)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self.cache_file, "wb") as handle:
                pickle.dump(self.cache, handle)
        except Exception as exc:
            logger.warning("Failed to save embeddings cache %s: %s", self.cache_file, exc)

    def get_local_trigram_embedding(self, text: str, dim: int | None = None) -> List[float]:
        target_dim = dim or self.trigram_dim
        text_clean = text.lower().strip()
        if not text_clean:
            return [0.0] * target_dim

        padded = f"_{text_clean}_"
        trigrams = [padded[index : index + 3] for index in range(len(padded) - 2)]
        vectors = []
        for trigram in trigrams:
            hash_val = int(hashlib.md5(trigram.encode("utf-8")).hexdigest(), 16)
            trigram_rng = np.random.default_rng(hash_val & 0xFFFFFFFF)
            vectors.append(trigram_rng.normal(0.0, 1.0, size=target_dim))

        summed = np.sum(vectors, axis=0)
        norm = np.linalg.norm(summed)
        if norm > 0:
            summed = summed / norm
        return summed.astype(float).tolist()

    def _get_yandex_client(self) -> YandexEmbeddingClient | None:
        if self._yandex_client is not None:
            return self._yandex_client
        try:
            config = resolve_yandex_config(env_file=self.env_file)
        except Exception:
            if YANDEX_API_KEY and self.folder_id:
                from backend.services.yandex_aistudio_client import YandexAIStudioConfig

                config = YandexAIStudioConfig(
                    api_key=YANDEX_API_KEY,
                    folder_id=self.folder_id,
                )
            else:
                return None
        self._yandex_client = YandexEmbeddingClient(config)
        return self._yandex_client

    async def _fetch_remote_embedding_async(self, text_key: str) -> List[float] | None:
        if os.environ.get("HSME_DISABLE_REMOTE_EMBEDDINGS") == "1":
            return None
        yandex_client = self._get_yandex_client()
        if yandex_client is not None:
            try:
                return await yandex_client.embed_async(text_key)
            except Exception as exc:
                logger.debug("Yandex embedding failed for %r: %s", text_key, exc.__class__.__name__)

        if self.client and "openrouter.ai" not in (self.base_url or ""):
            try:
                response = await self.client.embeddings.create(
                    input=[text_key],
                    model="text-embedding-3-small",
                )
                return [float(value) for value in response.data[0].embedding]
            except Exception as exc:
                logger.debug("OpenAI embedding failed for %r: %s", text_key, exc.__class__.__name__)
        return None

    def _fetch_remote_embedding_sync(self, text_key: str) -> List[float] | None:
        if os.environ.get("HSME_DISABLE_REMOTE_EMBEDDINGS") == "1":
            return None
        yandex_client = self._get_yandex_client()
        if yandex_client is not None:
            try:
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Api-Key {yandex_client.config.api_key}",
                }
                body = {
                    "modelUri": yandex_client.model_uri,
                    "text": text_key.strip(),
                }
                with httpx.Client(timeout=yandex_client.timeout_s) as client:
                    response = client.post(yandex_client.embedding_url, json=body, headers=headers)
                    response.raise_for_status()
                    payload = response.json()
                    embedding = payload.get("embedding")
                    if isinstance(embedding, list) and embedding:
                        return [float(value) for value in embedding]
            except Exception as exc:
                logger.debug("Sync Yandex embedding failed for %r: %s", text_key, exc.__class__.__name__)

        if self.api_key and self.base_url and "openrouter.ai" not in (self.base_url or ""):
            try:
                from openai import OpenAI
                sync_client = OpenAI(api_key=self.api_key, base_url=self.base_url)
                response = sync_client.embeddings.create(
                    input=[text_key],
                    model="text-embedding-3-small"
                )
                return [float(value) for value in response.data[0].embedding]
            except Exception as exc:
                logger.debug("Sync OpenAI embedding failed for %r: %s", text_key, exc.__class__.__name__)
        return None

    async def get_embedding_async(self, text: str) -> List[float]:
        text_key = text.strip()
        if text_key in self.cache:
            return self.cache[text_key]

        remote = await self._fetch_remote_embedding_async(text_key)
        if remote:
            self.cache[text_key] = remote
            self.save_cache()
            return remote

        embedding = self.get_local_trigram_embedding(text_key)
        self.cache[text_key] = embedding
        self.save_cache()
        return embedding

    def get_embedding_sync(self, text: str) -> List[float]:
        text_key = text.strip()
        if text_key in self.cache:
            return self.cache[text_key]

        remote = self._fetch_remote_embedding_sync(text_key)
        if remote:
            self.cache[text_key] = remote
            self.save_cache()
            return remote

        embedding = self.get_local_trigram_embedding(text_key)
        self.cache[text_key] = embedding
        self.save_cache()
        return embedding
