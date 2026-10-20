"""FR-A4 / FR-B1 向量库与 Top-K 检索单测（LocalVectorStore 后端）。"""

from __future__ import annotations

import pytest

from app.rag.text_embedding import MockEmbedder
from app.rag.text_index import (
    Hit,
    LocalVectorStore,
    VectorRecord,
    cosine_similarity,
    cosine_topk,
)


def make_records(embedder: MockEmbedder, doc_id: str = "doc-a", source: str = "选课办法.txt"):
    texts = [
        "每学期选课时间为开学前两周，每日八时至二十二时开放系统。",
        "学生可在补退选阶段申请退课，退课后不计入本学期学分。",
        "本科生每学期修读学分上限为三十学分，下限为十五学分。",
    ]
    vectors = embedder.embed_documents(texts)
    return [
        VectorRecord(
            id=f"{doc_id}:{i:05d}",
            doc_id=doc_id,
            source=source,
            page=f"第 {i + 1} 页",
            chunk_index=i,
            text=text,
            vector=vec,
            strategy="recursive",
        )
        for i, (text, vec) in enumerate(zip(texts, vectors))
    ]


@pytest.fixture
def embedder():
    return MockEmbedder(dim=256)


@pytest.fixture
def store(tmp_path, embedder):
    s = LocalVectorStore(root=tmp_path / "vs", collection="test_kb", dim=256)
    s.upsert(make_records(embedder))
    return s


def test_cosine_topk_matches_brute_force():
    vectors = [[1.0, 0.0], [0.9, 0.1], [0.0, 1.0], [-1.0, 0.0]]
    query = [1.0, 0.0]
    ranked = cosine_topk(query, vectors, top_k=3)
    brute = sorted(
        ((i, cosine_similarity(query, v)) for i, v in enumerate(vectors)),
        key=lambda x: x[1],
        reverse=True,
    )[:3]
    assert [i for i, _ in ranked] == [i for i, _ in brute]
    assert ranked[0][0] == 0
    assert ranked[0][1] == pytest.approx(1.0)


def test_cosine_topk_empty_vectors():
    assert cosine_topk([1.0, 0.0], [], top_k=3) == []


def test_cosine_topk_respects_k():
    vectors = [[1.0, 0.0], [0.5, 0.5], [0.0, 1.0]]
    assert len(cosine_topk([1.0, 0.0], vectors, top_k=2)) == 2


def test_store_count_and_search(store, embedder):
    assert store.count() == 3
    hits = store.search(embedder.embed_query("选课时间是多久"), top_k=2)
    assert len(hits) == 2
    assert all(isinstance(h, Hit) for h in hits)
    assert hits[0].score >= hits[1].score
    assert hits[0].source == "选课办法.txt"
    assert hits[0].page == "第 1 页"
    assert hits[0].id == "doc-a:00000"


def test_store_search_ranks_relevant_chunk_first(store, embedder):
    hits = store.search(embedder.embed_query("退课之后还算学分吗"), top_k=3)
    assert hits[0].chunk_index == 1


def test_store_empty_search_returns_no_hits(tmp_path, embedder):
    empty = LocalVectorStore(root=tmp_path / "empty", dim=256)
    assert empty.search(embedder.embed_query("随便问点什么"), top_k=3) == []
    assert empty.count() == 0


def test_upsert_same_id_does_not_duplicate(store, embedder):
    records = make_records(embedder)
    records[0].text = "改写后的第一条内容，用于验证覆盖写入。"
    store.upsert(records)
    # 同 id 覆盖：总块数不变，且新内容确实写进了向量库
    assert store.count() == 3
    hits = store.search(embedder.embed_query("改写后的第一条内容，用于验证覆盖写入"), top_k=3)
    assert any(h.text.startswith("改写后的第一条内容") for h in hits)
    assert len({h.id for h in hits}) == len(hits)


def test_delete_by_doc_removes_all_vectors(store, embedder):
    store.upsert(make_records(embedder, doc_id="doc-b", source="学籍规定.txt"))
    assert store.count() == 6
    removed = store.delete_by_doc("doc-a")
    assert removed == 3
    assert store.count() == 3
    # 已删除文档的内容不应再被检索到
    hits = store.search(embedder.embed_query("每学期选课时间为开学前两周"), top_k=3)
    assert all(h.doc_id == "doc-b" for h in hits)


def test_delete_unknown_doc_returns_zero(store):
    assert store.delete_by_doc("不存在") == 0


def test_delete_by_strategy(store, embedder):
    assert store.delete_by_strategy("recursive") == 3
    assert store.count() == 0


def test_list_documents_groups_by_doc(store, embedder):
    store.upsert(make_records(embedder, doc_id="doc-b", source="学籍规定.txt"))
    docs = {d["doc_id"]: d for d in store.list_documents()}
    assert set(docs) == {"doc-a", "doc-b"}
    assert docs["doc-a"]["chunk_count"] == 3
    assert docs["doc-a"]["source"] == "选课办法.txt"
    assert docs["doc-a"]["pages"] == ["第 1 页", "第 2 页", "第 3 页"]


def test_persistence_roundtrip(tmp_path, embedder):
    root = tmp_path / "persist"
    first = LocalVectorStore(root=root, dim=256)
    first.upsert(make_records(embedder))
    assert first.count() == 3

    second = LocalVectorStore(root=root, dim=256)
    assert second.count() == 3
    hits = second.search(embedder.embed_query("学分上限是多少"), top_k=1)
    assert hits[0].chunk_index == 2


def test_drop_clears_everything(store):
    store.drop()
    assert store.count() == 0


def test_record_fields_align_with_fr_a4(embedder):
    record = make_records(embedder)[0]
    data = record.to_dict()
    for key in ("id", "vector", "text", "source", "page", "chunk_index"):
        assert key in data, f"FR-A4 要求字段缺失: {key}"
    assert len(data["vector"]) == 256