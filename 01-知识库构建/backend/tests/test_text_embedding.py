"""FR-A3 嵌入与手算余弦相似度单测。"""

from __future__ import annotations

import math

import pytest

from app.rag.text_embedding import MockEmbedder, build_embedder, cosine_similarity


def test_cosine_similarity_known_values():
    assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine_similarity([1, 0], [-1, 0]) == pytest.approx(-1.0)
    assert cosine_similarity([3, 4], [3, 4]) == pytest.approx(1.0)


def test_cosine_similarity_zero_vector_is_zero():
    assert cosine_similarity([0, 0], [1, 1]) == 0.0


def test_cosine_similarity_dimension_mismatch_raises():
    with pytest.raises(ValueError, match="维度不一致"):
        cosine_similarity([1, 2], [1, 2, 3])


def test_mock_embedder_is_deterministic_and_normalized():
    embedder = MockEmbedder(dim=64)
    a = embedder.embed_query("选课什么时候开始")
    b = embedder.embed_query("选课什么时候开始")
    assert a == b
    assert len(a) == 64
    assert math.isclose(math.sqrt(sum(x * x for x in a)), 1.0, rel_tol=1e-6)


def test_mock_embedder_ranks_similar_text_higher():
    embedder = MockEmbedder(dim=256)
    query = embedder.embed_query("选课什么时候开始")
    related = embedder.embed_query("每学期的选课时间在开学前两周开放")
    unrelated = embedder.embed_query("食堂几点关门")
    assert cosine_similarity(query, related) > cosine_similarity(query, unrelated)


def test_mock_embedder_batch_matches_single():
    embedder = MockEmbedder(dim=32)
    texts = ["甲乙丙", "丁戊己"]
    batch = embedder.embed_documents(texts)
    assert batch == [embedder.embed_query(t) for t in texts]


def test_build_embedder_mock_provider():
    embedder = build_embedder(provider="mock", dimensions=32)
    assert embedder.name == "mock"
    assert embedder.dim == 32


def test_build_embedder_falls_back_to_mock_without_key(monkeypatch):
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    embedder = build_embedder(provider="dashscope", api_key="", allow_mock=True)
    assert embedder.name == "mock"


def test_build_embedder_raises_without_key_when_mock_disabled(monkeypatch):
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="未配置"):
        build_embedder(provider="dashscope", api_key="", allow_mock=False)