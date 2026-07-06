import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.nlp_extractor import (
    NLPExtractor,
    extract_json_payload,
    is_moderation_refusal,
    normalize_message_content,
    parse_llm_json,
    repair_json_text,
    uses_yandex_json_mode,
)


def test_normalize_message_content_handles_string():
    assert normalize_message_content(' {"entities": []} ') == '{"entities": []}'


def test_normalize_message_content_handles_parts_list():
    content = [{"type": "text", "text": '{"entities": []}'}]
    assert normalize_message_content(content) == '{"entities": []}'


def test_normalize_message_content_empty():
    assert normalize_message_content(None) == ""
    assert normalize_message_content("   ") == ""


def test_extract_json_payload_from_markdown_fence():
    text = 'Вот результат:\n```json\n{"entities": [], "relations": []}\n```'
    assert json.loads(extract_json_payload(text)) == {"entities": [], "relations": []}


def test_extract_json_payload_from_plain_object():
    text = 'prefix {"entities": [{"type": "Material", "value": "Ni"}]} suffix'
    payload = extract_json_payload(text)
    assert json.loads(payload)["entities"][0]["value"] == "Ni"


def test_extract_json_payload_empty():
    assert extract_json_payload("") == ""
    assert extract_json_payload("no json here") == "no json here"


def test_parse_llm_json_allows_control_characters_in_strings():
    payload = parse_llm_json('{"entities": [{"type": "Property", "value": "pH\n2.0"}]}')
    assert payload["entities"][0]["value"] == "pH\n2.0"


def test_repair_json_text_removes_trailing_commas():
    raw = '{"entities": [{"type": "Material", "value": "Ni",},], "relations": [],}'
    payload = parse_llm_json(raw)
    assert payload["entities"][0]["value"] == "Ni"


def test_parse_llm_json_normalizes_smart_quotes():
    raw = '{"entities": [{"type": "Material", "value": “никель”}], "relations": []}'
    payload = parse_llm_json(raw)
    assert payload["entities"][0]["value"] == "никель"


def test_uses_yandex_json_mode():
    assert uses_yandex_json_mode("gpt://b1g/yandexgpt-5.1/latest", use_gemini=False) is True
    assert uses_yandex_json_mode("openai/gpt-4o-mini", use_gemini=False) is False
    assert uses_yandex_json_mode("gpt://b1g/yandexgpt-5.1/latest", use_gemini=True) is False


@pytest.mark.asyncio
async def test_extract_entities_requests_json_object_for_yandex():
    extractor = NLPExtractor(
        api_key="AQVNtest",
        folder_id="b1gtest",
        base_url="https://ai.api.cloud.yandex.net/v1",
        model_id="gpt://b1gtest/yandexgpt-5.1/latest",
    )
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content='{"entities": [{"type": "Material", "value": "никель"}], "relations": []}'
            )
        )
    ]
    extractor.client.chat.completions.create = AsyncMock(return_value=mock_response)

    result = await extractor.extract_entities_and_relations("текст про никель")

    assert result["entities"][0]["value"] == "никель"
    assert result["relations"] == []
    kwargs = extractor.client.chat.completions.create.await_args.kwargs
    assert kwargs["response_format"] == {"type": "json_object"}
    assert "extra_headers" not in kwargs


@pytest.mark.asyncio
async def test_extract_entities_retries_on_validation_error():
    extractor = NLPExtractor(
        api_key="AQVNtest",
        folder_id="b1gtest",
        base_url="https://ai.api.cloud.yandex.net/v1",
        model_id="gpt://b1gtest/yandexgpt-5.1/latest",
    )
    invalid = MagicMock()
    invalid.choices = [
        MagicMock(
            message=MagicMock(
                content='{"entities": [{"type": "Unknown", "value": "x"}], "relations": []}'
            )
        )
    ]
    good = MagicMock()
    good.choices = [
        MagicMock(
            message=MagicMock(
                content='{"entities": [{"type": "Material", "value": "никель"}], "relations": []}'
            )
        )
    ]
    extractor.client.chat.completions.create = AsyncMock(side_effect=[invalid, good])

    with patch("backend.services.nlp_extractor.asyncio.sleep", new=AsyncMock()):
        result = await extractor.extract_entities_and_relations("никель")

    assert result["entities"][0]["value"] == "никель"
    assert extractor.client.chat.completions.create.await_count == 2


def test_detect_moderation_refusal():
    assert is_moderation_refusal("Я не могу обсуждать эту тему. Давайте поговорим о чём-нибудь ещё.")
    assert not is_moderation_refusal('{"entities": [], "relations": []}')


@pytest.mark.asyncio
async def test_extract_moderation_retries_then_empty():
    extractor = NLPExtractor(
        api_key="AQVNtest",
        folder_id="b1gtest",
        base_url="https://ai.api.cloud.yandex.net/v1",
        model_id="gpt://b1gtest/yandexgpt-5.1/latest",
    )
    refusal = MagicMock()
    refusal.choices = [
        MagicMock(
            message=MagicMock(
                content="Я не могу обсуждать эту тему. Давайте поговорим о чём-нибудь ещё."
            )
        )
    ]
    extractor.client.chat.completions.create = AsyncMock(side_effect=[refusal, refusal, refusal])

    with patch("backend.services.nlp_extractor.asyncio.sleep", new=AsyncMock()):
        result = await extractor.extract_entities_and_relations("U Pu UF6")

    assert result == {"entities": [], "relations": [], "_skip_reason": "moderation"}
    assert extractor.client.chat.completions.create.await_count == 3


@pytest.mark.asyncio
async def test_extract_partial_validation_no_retry():
    extractor = NLPExtractor(
        api_key="AQVNtest",
        folder_id="b1gtest",
        base_url="https://ai.api.cloud.yandex.net/v1",
        model_id="gpt://b1gtest/yandexgpt-5.1/latest",
    )
    partial = MagicMock()
    partial.choices = [
        MagicMock(
            message=MagicMock(
                content=(
                    '{"entities": [{"type": "Material", "value": "сера"}], '
                    '"relations": [{"source": "a", "type": "depends_on", "target": "b"}]}'
                )
            )
        )
    ]
    extractor.client.chat.completions.create = AsyncMock(return_value=partial)

    result = await extractor.extract_entities_and_relations("сера")

    assert result["entities"][0]["value"] == "сера"
    assert result["relations"] == []
    assert extractor.client.chat.completions.create.await_count == 1


@pytest.mark.asyncio
async def test_extract_moderation_retry_succeeds():
    extractor = NLPExtractor(
        api_key="AQVNtest",
        folder_id="b1gtest",
        base_url="https://ai.api.cloud.yandex.net/v1",
        model_id="gpt://b1gtest/yandexgpt-5.1/latest",
    )
    refusal = MagicMock()
    refusal.choices = [
        MagicMock(
            message=MagicMock(
                content="Я не могу обсуждать эту тему. Давайте поговорим о чём-нибудь ещё."
            )
        )
    ]
    good = MagicMock()
    good.choices = [
        MagicMock(
            message=MagicMock(
                content='{"entities": [{"type": "Material", "value": "U"}], "relations": []}'
            )
        )
    ]
    extractor.client.chat.completions.create = AsyncMock(side_effect=[refusal, good])

    with patch("backend.services.nlp_extractor.asyncio.sleep", new=AsyncMock()):
        result = await extractor.extract_entities_and_relations("uranium metallurgy")

    assert result["entities"][0]["value"] == "U"
    assert extractor.client.chat.completions.create.await_count == 2


@pytest.mark.asyncio
async def test_extract_entities_retries_on_invalid_json():
    extractor = NLPExtractor(
        api_key="AQVNtest",
        folder_id="b1gtest",
        base_url="https://ai.api.cloud.yandex.net/v1",
        model_id="gpt://b1gtest/yandexgpt-5.1/latest",
    )
    bad = MagicMock()
    bad.choices = [MagicMock(message=MagicMock(content="not json"))]
    good = MagicMock()
    good.choices = [
        MagicMock(
            message=MagicMock(
                content='{"entities": [{"type": "Material", "value": "никель"}], "relations": []}'
            )
        )
    ]
    extractor.client.chat.completions.create = AsyncMock(side_effect=[bad, good])

    with patch("backend.services.nlp_extractor.asyncio.sleep", new=AsyncMock()):
        result = await extractor.extract_entities_and_relations("никель")

    assert result["entities"][0]["value"] == "никель"
    assert extractor.client.chat.completions.create.await_count == 2
