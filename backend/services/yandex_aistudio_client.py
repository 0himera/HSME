"""Minimal Yandex AI Studio client for credential smoke tests.

Docs:
- https://aistudio.yandex.ru/docs/ru/ai-studio/quickstart/
- https://aistudio.yandex.ru/docs/en/ai-studio/operations/models/get
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from openai import APIStatusError, AuthenticationError, NotFoundError, OpenAI

from backend.core.config import (
    YANDEX_BASE_URL,
    read_env_file,
)

DEFAULT_BASE_URL = YANDEX_BASE_URL
DEFAULT_MODEL_SLUG = "yandexgpt-5.1/latest"
DEFAULT_TEST_PROMPT = "Ответь одним словом: какой химический символ у водорода?"


class YandexAIStudioError(Exception):
    """Base error for Yandex AI Studio helpers."""


class YandexAIStudioConfigError(YandexAIStudioError):
    """Missing or invalid local configuration."""


class YandexAIStudioAPIError(YandexAIStudioError):
    """Remote API returned an error."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class YandexAIStudioConfig:
    api_key: str
    folder_id: str
    base_url: str = DEFAULT_BASE_URL
    model_slug: str = DEFAULT_MODEL_SLUG

    @property
    def model_uri(self) -> str:
        return build_model_uri(self.folder_id, self.model_slug)


def build_model_uri(folder_id: str, model_slug: str) -> str:
    slug = model_slug.removeprefix("gpt://")
    if "/" in slug and slug.startswith(folder_id):
        return f"gpt://{slug}"
    return f"gpt://{folder_id}/{slug}"


def resolve_yandex_config(
    *,
    api_key: str | None = None,
    folder_id: str | None = None,
    base_url: str | None = None,
    model_slug: str | None = None,
    env_file: str | None = None,
) -> YandexAIStudioConfig:
    """Merge Yandex creds from CLI args, process env, and optional .env file."""
    file_values = read_env_file(env_file or ".env")

    def pick(*names: str, cli_value: str | None = None) -> str | None:
        if cli_value:
            return cli_value
        for name in names:
            env_value = os.environ.get(name)
            if env_value:
                return env_value
        for name in names:
            file_value = file_values.get(name)
            if file_value:
                return file_value
        return None

    resolved_api_key = pick(
        "YANDEX_API_KEY",
        "LLM_API_KEY",
        cli_value=api_key,
    ) or ""

    resolved_folder_id = pick(
        "YANDEX_FOLDER_ID",
        "LLM_FOLDER_ID",
        cli_value=folder_id,
    ) or ""

    resolved_base_url = pick(
        "YANDEX_BASE_URL",
        cli_value=base_url,
    ) or DEFAULT_BASE_URL

    resolved_model_slug = pick("YANDEX_MODEL", cli_value=model_slug)
    if not resolved_model_slug:
        llm_model = pick("LLM_MODEL", "LLM_MODEL_ID")
        if llm_model and llm_model.startswith("gpt://"):
            resolved_model_slug = llm_model
    if resolved_model_slug and resolved_model_slug.startswith("gpt://"):
        _, _, tail = resolved_model_slug.partition("gpt://")
        if "/" in tail:
            resolved_model_slug = tail.split("/", 1)[1]
    if not resolved_model_slug:
        resolved_model_slug = DEFAULT_MODEL_SLUG

    if not resolved_api_key or resolved_api_key in ("", "your_yandex_api_key_here"):
        raise YandexAIStudioConfigError(
            "YANDEX_API_KEY or LLM_API_KEY is missing. "
            "Set it in the environment or .env file."
        )
    if not resolved_folder_id or resolved_folder_id in ("", "your_yandex_folder_id_here"):
        raise YandexAIStudioConfigError(
            "YANDEX_FOLDER_ID or LLM_FOLDER_ID is missing. "
            "Copy the folder ID from AI Studio UI."
        )

    return YandexAIStudioConfig(
        api_key=resolved_api_key,
        folder_id=resolved_folder_id,
        base_url=resolved_base_url.rstrip("/"),
        model_slug=resolved_model_slug,
    )


class YandexAIStudioClient:
    def __init__(self, config: YandexAIStudioConfig, *, client: OpenAI | None = None):
        self.config = config
        self._client = client or OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            project=config.folder_id,
        )

    def list_models(self) -> list[dict[str, Any]]:
        try:
            response = self._client.models.list()
        except AuthenticationError as exc:
            raise YandexAIStudioAPIError(
                "Authentication failed. Check YANDEX_API_KEY / LLM_API_KEY.",
                status_code=401,
            ) from exc
        except APIStatusError as exc:
            raise YandexAIStudioAPIError(str(exc), status_code=exc.status_code) from exc

        return [
            {
                "id": model.id,
                "object": getattr(model, "object", "model"),
                "owned_by": getattr(model, "owned_by", None),
            }
            for model in response.data
        ]

    def ask(
        self,
        prompt: str = DEFAULT_TEST_PROMPT,
        *,
        temperature: float = 0.2,
        max_tokens: int = 64,
        model_slug: str | None = None,
    ) -> str:
        model_uri = build_model_uri(
            self.config.folder_id,
            model_slug or self.config.model_slug,
        )
        try:
            response = self._client.chat.completions.create(
                model=model_uri,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except AuthenticationError as exc:
            raise YandexAIStudioAPIError(
                "Authentication failed. Check YANDEX_API_KEY / LLM_API_KEY.",
                status_code=401,
            ) from exc
        except NotFoundError as exc:
            raise YandexAIStudioAPIError(
                f"Model not found: {model_uri}",
                status_code=404,
            ) from exc
        except APIStatusError as exc:
            raise YandexAIStudioAPIError(str(exc), status_code=exc.status_code) from exc

        if not response.choices:
            raise YandexAIStudioAPIError("Model returned no choices.")

        content = response.choices[0].message.content
        if not content or not content.strip():
            raise YandexAIStudioAPIError("Model returned an empty answer.")
        return content.strip()
