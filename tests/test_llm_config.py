import os
import tempfile

from backend.core.config import read_env_file, resolve_llm_settings


def test_read_env_file_parses_key_value_pairs():
    with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False, encoding="utf-8") as handle:
        handle.write("# comment\n")
        handle.write('LLM_API_KEY="secret-key"\n')
        handle.write("LLM_BASE_URL=https://example.com/v1\n")
        path = handle.name

    try:
        values = read_env_file(path)
        assert values["LLM_API_KEY"] == "secret-key"
        assert values["LLM_BASE_URL"] == "https://example.com/v1"
    finally:
        os.remove(path)


def test_resolve_llm_settings_cli_overrides_file():
    with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False, encoding="utf-8") as handle:
        handle.write("LLM_API_KEY=file-key\n")
        handle.write("LLM_BASE_URL=https://file.example/v1\n")
        path = handle.name

    try:
        resolved = resolve_llm_settings(
            api_key="cli-key",
            base_url="https://cli.example/v1",
            env_file=path,
        )
        assert resolved["LLM_API_KEY"] == "cli-key"
        assert resolved["LLM_BASE_URL"] == "https://cli.example/v1"
    finally:
        os.remove(path)


def test_resolve_llm_settings_reads_from_file_when_cli_missing():
    with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False, encoding="utf-8") as handle:
        handle.write("LLM_API_KEY=file-key\n")
        handle.write("LLM_BASE_URL=https://file.example/v1\n")
        path = handle.name

    try:
        from unittest.mock import patch
        with patch.dict(os.environ, {}, clear=True):
            resolved = resolve_llm_settings(env_file=path)
            assert resolved["LLM_API_KEY"] == "file-key"
            assert resolved["LLM_BASE_URL"] == "https://file.example/v1"
    finally:
        os.remove(path)


def test_resolve_llm_settings_reads_model_alias_from_file():
    with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False, encoding="utf-8") as handle:
        handle.write("LLM_MODEL=openai/gpt-4o-mini\n")
        path = handle.name

    try:
        from unittest.mock import patch
        with patch.dict(os.environ, {}, clear=True):
            resolved = resolve_llm_settings(env_file=path)
            assert resolved["LLM_MODEL_ID"] == "openai/gpt-4o-mini"
    finally:
        os.remove(path)
