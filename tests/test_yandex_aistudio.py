import os
from unittest.mock import MagicMock

import pytest
from openai import AuthenticationError, NotFoundError

from backend.services.yandex_aistudio_client import (
    YandexAIStudioAPIError,
    YandexAIStudioClient,
    YandexAIStudioConfig,
    YandexAIStudioConfigError,
    build_model_uri,
    resolve_yandex_config,
)


def _make_config(**overrides) -> YandexAIStudioConfig:
    defaults = {
        "api_key": "AQVNtest-key",
        "folder_id": "b1gtestfolder",
        "base_url": "https://ai.api.cloud.yandex.net/v1",
        "model_slug": "yandexgpt-5.1/latest",
    }
    defaults.update(overrides)
    return YandexAIStudioConfig(**defaults)


def test_build_model_uri_from_slug():
    assert build_model_uri("b1gabc", "yandexgpt-5.1/latest") == (
        "gpt://b1gabc/yandexgpt-5.1/latest"
    )


def test_build_model_uri_keeps_full_uri():
    uri = "gpt://b1gabc/yandexgpt-5.1/latest"
    assert build_model_uri("b1gabc", uri) == uri


def test_resolve_config_from_explicit_values():
    config = resolve_yandex_config(
        api_key="AQVNcli",
        folder_id="b1gcli",
        base_url="https://ai.api.cloud.yandex.net/v1",
        model_slug="yandexgpt-5.1/latest",
        env_file="/nonexistent/.env",
    )
    assert config.api_key == "AQVNcli"
    assert config.folder_id == "b1gcli"
    assert config.model_uri == "gpt://b1gcli/yandexgpt-5.1/latest"


def _clear_yandex_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "YANDEX_API_KEY",
        "YANDEX_FOLDER_ID",
        "LLM_API_KEY",
        "LLM_FOLDER_ID",
        "YANDEX_BASE_URL",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "LLM_MODEL_ID",
    ):
        monkeypatch.delenv(name, raising=False)


def test_resolve_config_uses_yandex_base_url_not_llm_base_url(tmp_path, monkeypatch):
    _clear_yandex_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "YANDEX_API_KEY=AQVNfile\n"
        "YANDEX_FOLDER_ID=b1gfile\n"
        "YANDEX_BASE_URL=https://custom.yandex.example/v1\n"
        "LLM_BASE_URL=https://proxy.example/v1\n",
        encoding="utf-8",
    )
    config = resolve_yandex_config(env_file=str(env_file))
    assert config.base_url == "https://custom.yandex.example/v1"


def test_resolve_config_ignores_non_yandex_llm_model(tmp_path, monkeypatch):
    _clear_yandex_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "YANDEX_API_KEY=AQVNfile\n"
        "YANDEX_FOLDER_ID=b1gfile\n"
        "LLM_MODEL=gpt-4o-mini\n",
        encoding="utf-8",
    )
    config = resolve_yandex_config(env_file=str(env_file))
    assert config.model_slug == "yandexgpt-5.1/latest"
    assert config.model_uri == "gpt://b1gfile/yandexgpt-5.1/latest"


def test_resolve_config_uses_yandex_model_env(tmp_path, monkeypatch):
    _clear_yandex_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "YANDEX_API_KEY=AQVNfile\n"
        "YANDEX_FOLDER_ID=b1gfile\n"
        "YANDEX_MODEL=yandexgpt-5-pro/latest\n"
        "LLM_MODEL=gpt-4o-mini\n",
        encoding="utf-8",
    )
    config = resolve_yandex_config(env_file=str(env_file))
    assert config.model_slug == "yandexgpt-5-pro/latest"


def test_resolve_config_parses_full_model_uri(tmp_path, monkeypatch):
    _clear_yandex_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "YANDEX_API_KEY=AQVNfile\n"
        "YANDEX_FOLDER_ID=b1gfile\n"
        "LLM_MODEL=gpt://b1gfile/yandexgpt-5.1/latest\n",
        encoding="utf-8",
    )
    config = resolve_yandex_config(env_file=str(env_file))
    assert config.api_key == "AQVNfile"
    assert config.folder_id == "b1gfile"
    assert config.model_slug == "yandexgpt-5.1/latest"


def test_resolve_config_raises_when_api_key_missing(monkeypatch):
    _clear_yandex_env(monkeypatch)
    with pytest.raises(YandexAIStudioConfigError, match="LLM_API_KEY"):
        resolve_yandex_config(
            api_key="",
            folder_id="b1gabc",
            env_file="/nonexistent/.env",
        )


def test_resolve_config_raises_when_folder_id_missing(monkeypatch):
    _clear_yandex_env(monkeypatch)
    with pytest.raises(YandexAIStudioConfigError, match="FOLDER_ID"):
        resolve_yandex_config(
            api_key="AQVNtest",
            folder_id="",
            env_file="/nonexistent/.env",
        )


def test_list_models_success():
    mock_client = MagicMock()
    mock_client.models.list.return_value.data = [
        MagicMock(
            id="gpt://b1gabc/yandexgpt-5.1/latest",
            object="model",
            owned_by="Yandex",
        ),
        MagicMock(
            id="gpt://b1gabc/aliceai-llm/latest",
            object="model",
            owned_by="Yandex",
        ),
    ]

    client = YandexAIStudioClient(_make_config(), client=mock_client)
    models = client.list_models()

    assert len(models) == 2
    assert models[0]["id"] == "gpt://b1gabc/yandexgpt-5.1/latest"
    mock_client.models.list.assert_called_once_with()


def test_list_models_unauthorized():
    mock_client = MagicMock()
    mock_client.models.list.side_effect = AuthenticationError(
        message="invalid api key",
        response=MagicMock(status_code=401),
        body=None,
    )

    client = YandexAIStudioClient(_make_config(), client=mock_client)

    with pytest.raises(YandexAIStudioAPIError, match="Authentication failed") as exc:
        client.list_models()
    assert exc.value.status_code == 401


def test_ask_yandexgpt_success():
    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "H"
    mock_client.chat.completions.create.return_value.choices = [mock_choice]

    client = YandexAIStudioClient(_make_config(), client=mock_client)
    answer = client.ask("Какой символ у водорода?")

    assert answer == "H"
    mock_client.chat.completions.create.assert_called_once_with(
        model="gpt://b1gtestfolder/yandexgpt-5.1/latest",
        messages=[{"role": "user", "content": "Какой символ у водорода?"}],
        temperature=0.2,
        max_tokens=64,
    )


def test_ask_yandexgpt_model_not_found():
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = NotFoundError(
        message="model not found",
        response=MagicMock(status_code=404),
        body=None,
    )

    client = YandexAIStudioClient(_make_config(), client=mock_client)

    with pytest.raises(YandexAIStudioAPIError, match="Model not found") as exc:
        client.ask("ping")
    assert exc.value.status_code == 404


def test_ask_yandexgpt_empty_answer():
    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "   "
    mock_client.chat.completions.create.return_value.choices = [mock_choice]

    client = YandexAIStudioClient(_make_config(), client=mock_client)

    with pytest.raises(YandexAIStudioAPIError, match="empty answer"):
        client.ask("ping")


def _has_live_yandex_creds() -> bool:
    api_key = os.environ.get("YANDEX_API_KEY") or os.environ.get("LLM_API_KEY") or ""
    folder_id = os.environ.get("YANDEX_FOLDER_ID") or os.environ.get("LLM_FOLDER_ID") or ""
    if not api_key or not folder_id:
        return False
    if api_key.startswith("sk-"):
        return False
    return True


@pytest.mark.integration
@pytest.mark.skipif(not _has_live_yandex_creds(), reason="Yandex AI Studio creds not configured")
def test_integration_list_models_and_ask():
    config = resolve_yandex_config()
    client = YandexAIStudioClient(config)

    models = client.list_models()
    assert models
    assert any("yandexgpt" in model["id"] for model in models)

    answer = client.ask("Ответь одним словом: какой химический символ у водорода?")
    assert answer
    assert "H" in answer.upper()
