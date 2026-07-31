import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.services.yandex_embedding import (
    YandexEmbeddingClient,
    cosine_similarity,
    run_smoke,
)
from backend.services.yandex_aistudio_client import (
    YandexAIStudioAPIError,
    YandexAIStudioConfig,
)


def _make_config() -> YandexAIStudioConfig:
    return YandexAIStudioConfig(
        api_key="AQVNtest-key",
        folder_id="b1gtestfolder",
    )


@pytest.mark.asyncio
async def test_embed_async_happy_path():
    client = YandexEmbeddingClient(_make_config())

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"embedding": [0.1, -0.2, 0.3]}

    mock_http = AsyncMock()
    mock_http.post.return_value = mock_response
    mock_http.__aenter__.return_value = mock_http
    mock_http.__aexit__.return_value = None

    with patch("backend.services.yandex_embedding.httpx.AsyncClient", return_value=mock_http):
        vector = await client.embed_async("никель")

    assert vector == [0.1, -0.2, 0.3]
    assert client.model_uri == "emb://b1gtestfolder/text-search-query/latest"
    mock_http.post.assert_awaited_once()
    call_kwargs = mock_http.post.await_args.kwargs
    assert call_kwargs["json"]["text"] == "никель"
    assert call_kwargs["headers"]["Authorization"] == "Api-Key AQVNtest-key"


@pytest.mark.asyncio
async def test_embed_async_auth_error():
    client = YandexEmbeddingClient(_make_config())

    request = httpx.Request("POST", client.embedding_url)
    response = httpx.Response(401, request=request, text='{"error":"Unauthorized"}')
    http_error = httpx.HTTPStatusError("Unauthorized", request=request, response=response)

    mock_http = AsyncMock()
    mock_http.post.side_effect = http_error
    mock_http.__aenter__.return_value = mock_http
    mock_http.__aexit__.return_value = None

    with patch("backend.services.yandex_embedding.httpx.AsyncClient", return_value=mock_http):
        with pytest.raises(YandexAIStudioAPIError, match="401"):
            await client.embed_async("nickel")


@pytest.mark.asyncio
async def test_embed_async_missing_embedding_field():
    client = YandexEmbeddingClient(_make_config())

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"result": "unexpected"}

    mock_http = AsyncMock()
    mock_http.post.return_value = mock_response
    mock_http.__aenter__.return_value = mock_http
    mock_http.__aexit__.return_value = None

    with patch("backend.services.yandex_embedding.httpx.AsyncClient", return_value=mock_http):
        with pytest.raises(YandexAIStudioAPIError, match="missing non-empty 'embedding'"):
            await client.embed_async("nickel")


def test_cosine_similarity_identical_vectors():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_cosine_similarity_dimension_mismatch():
    with pytest.raises(ValueError, match="dimensions differ"):
        cosine_similarity([1.0], [1.0, 0.0])


def _has_live_yandex_creds() -> bool:
    api_key = os.environ.get("YANDEX_API_KEY") or os.environ.get("LLM_API_KEY") or ""
    folder_id = os.environ.get("YANDEX_FOLDER_ID") or os.environ.get("LLM_FOLDER_ID") or ""
    if not api_key or not folder_id:
        return False
    if api_key.startswith("sk-"):
        return False
    return True


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(not _has_live_yandex_creds(), reason="Yandex creds not configured")
async def test_integration_yandex_search_query_embedding():
    result = await run_smoke()
    assert result["vector_dim"] > 0
    assert "никель vs nickel" in result["similarity"]
    assert result["similarity"]["никель vs nickel"] > result["similarity"]["никель vs кучное выщелачивание"]
