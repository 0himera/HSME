import time
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from backend.core.models import Entity
from backend.repository.database import HSMEVectorDatabase
from backend.services.embedding import (
    BipolarProjection,
    EmbeddingService,
    is_semantic_entity_key,
    normalize_entity_key,
    normalize_entity_value,
)


@pytest.fixture
def embedding_cache_file(tmp_path):
    return str(tmp_path / "embeddings_cache.pkl")


@pytest.fixture
def semantic_db(embedding_cache_file):
    service = EmbeddingService(cache_file=embedding_cache_file)
    return HSMEVectorDatabase(dim=10000, embedding_service=service)


def test_is_semantic_entity_key():
    assert is_semantic_entity_key("Material:никель") is True
    assert is_semantic_entity_key("Role:Material") is False
    assert is_semantic_entity_key("RelationType:uses_material") is False
    assert is_semantic_entity_key("NumericBase:ph:min") is False


def test_normalize_entity_key_collapses_case_and_whitespace():
    assert normalize_entity_value("  Никель  ") == "никель"
    assert normalize_entity_key("Material:Никель") == "Material:никель"
    assert normalize_entity_key("Material:Nickel") == "Material:nickel"
    assert normalize_entity_key("Property:10\xa0г/л") == "Property:10 г/л"
    assert normalize_entity_key("Role:Material") == "Role:Material"
    assert normalize_entity_key("NumericBase:pH:min") == "NumericBase:ph:min"


def test_case_variants_share_same_codebook_vector(semantic_db):
    v_upper = semantic_db.get_or_create_vector("Material:Никель")
    v_lower = semantic_db.get_or_create_vector("Material:никель")
    assert np.array_equal(v_upper, v_lower)
    assert "Material:никель" in semantic_db.codebook
    assert "Material:Никель" not in semantic_db.codebook


def test_bipolar_projection_is_deterministic():
    projection_a = BipolarProjection(vsa_dim=10000, seed=12345)
    projection_b = BipolarProjection(vsa_dim=10000, seed=12345)
    dense = [0.1, -0.2, 0.3, 0.05] * 64

    vector_a = projection_a.project(dense)
    vector_b = projection_b.project(dense)

    assert np.array_equal(vector_a, vector_b)
    assert vector_a.shape == (10000,)
    assert set(np.unique(vector_a)).issubset({-1, 1})


def test_bilingual_synonym_proximity_with_cached_embeddings(semantic_db):
    service = semantic_db.embedding_service
    base = [0.02] * 256
    service.cache["никель"] = base
    service.cache["nickel"] = [value + 0.001 for value in base]
    service.cache["флотация"] = [-0.5 if index % 2 == 0 else 0.4 for index in range(256)]

    v_nickel_ru = semantic_db.get_or_create_vector("Material:Никель")
    v_nickel_en = semantic_db.get_or_create_vector("Material:Nickel")
    v_flotation = semantic_db.get_or_create_vector("Process:Флотация")

    sim_ru_en = semantic_db.vsa.similarity(v_nickel_ru, v_nickel_en)
    sim_ru_flotation = semantic_db.vsa.similarity(v_nickel_ru, v_flotation)

    assert sim_ru_en > 0.4
    assert sim_ru_en > sim_ru_flotation


def test_embedding_api_failure_falls_back_to_trigram(embedding_cache_file):
    service = EmbeddingService(cache_file=embedding_cache_file)

    with patch.object(service, "_fetch_remote_embedding_async", new=AsyncMock(return_value=None)):
        embedding = service.get_embedding_sync("никель")

    assert len(embedding) == 384
    assert "никель" in service.cache
    vector = BipolarProjection().project(embedding)
    assert vector.shape == (10000,)


def test_empty_and_special_character_inputs_are_stable(embedding_cache_file):
    service = EmbeddingService(cache_file=embedding_cache_file)
    projection = BipolarProjection(vsa_dim=1000)

    for text in ["", "   ", "Ni²⁺", "электро-экстракция", "a" * 500]:
        dense = service.get_embedding_sync(text)
        vector = projection.project(dense)
        assert len(dense) == 384
        assert vector.shape == (1000,)
        assert set(np.unique(vector)).issubset({-1, 1})


def test_cached_vector_lookup_is_fast(semantic_db):
    semantic_db.get_or_create_vector("Material:никель")

    start = time.perf_counter()
    for _ in range(1000):
        semantic_db.get_or_create_vector("Material:Никель")
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert elapsed_ms < 50


def test_meta_keys_still_use_random_orthogonal_vectors(semantic_db):
    role_a = semantic_db.get_or_create_vector("Role:Material")
    role_b = semantic_db.get_or_create_vector("Role:Process")
    assert abs(semantic_db.vsa.similarity(role_a, role_b)) < 0.1
