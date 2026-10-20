"""拒答判定与向量维度校验单测（真机联调中发现并修复的两个问题）。"""

from __future__ import annotations

import pytest

from app.rag.text_chat import MockChatModel
from app.rag.text_embedding import MockEmbedder
from app.rag.text_index import LocalVectorStore, VectorDimensionMismatch, VectorRecord
from app.rag.text_rag import ANSWER_NOT_FOUND, RagPipeline, looks_like_refusal


# ---------------------------------------------------------------------------
# 模型层拒答识别
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "answer",
    [
        ANSWER_NOT_FOUND,
        "知识库中未找到相关依据。",
        "根据现有材料无法回答该问题。",
        "上述材料未提及食堂的营业时间。",
        "材料中没有相关内容，无法作答。",
    ],
)
def test_looks_like_refusal_detects_declinations(answer):
    assert looks_like_refusal(answer) is True


@pytest.mark.parametrize(
    "answer",
    [
        "选课时间为开学前两周【1】。",
        "",
        "   ",
        "本科生每学期修读学分上限为三十学分【2】。",
    ],
)
def test_looks_like_refusal_rejects_normal_answers(answer):
    assert looks_like_refusal(answer) is False


class StubChatModel(MockChatModel):
    """无论材料是否相关，都固定回一句拒答——用于模拟「模型层拒答」。"""

    def __init__(self, answer: str = "知识库中未找到相关依据。") -> None:
        super().__init__()
        self._answer = answer

    def stream(self, messages, **kwargs):
        yield self._answer


def _pipeline_with(store, chat_model, threshold=0.0):
    return RagPipeline(
        embedder=MockEmbedder(dim=128),
        store=store,
        chat_model=chat_model,
        top_k=3,
        score_threshold=threshold,
    )


def _store_with_one_chunk(tmp_path):
    embedder = MockEmbedder(dim=128)
    store = LocalVectorStore(root=tmp_path / "vs", dim=128)
    text = "每学期选课时间为开学前两周。"
    store.upsert(
        [
            VectorRecord(
                id="d:00000",
                doc_id="d",
                source="选课办法.txt",
                page="第 1 页",
                chunk_index=0,
                text=text,
                vector=embedder.embed_query(text),
            )
        ]
    )
    return store, embedder


def test_model_level_refusal_marks_done_event(tmp_path):
    """材料过了阈值但模型自行拒答时，refused 必须为 True 且不保留 hit_ids。"""
    store, _ = _store_with_one_chunk(tmp_path)
    pipeline = _pipeline_with(store, StubChatModel())

    done = [e for e in pipeline.ask_stream("食堂几点关门") if e.type == "done"][-1]
    assert done.data["refused"] is True
    assert done.data["hit_ids"] == []
    assert done.data["hits"] == []
    assert "知识库中未找到相关依据" in done.data["answer"]


def test_normal_answer_keeps_hits(tmp_path):
    store, _ = _store_with_one_chunk(tmp_path)
    pipeline = _pipeline_with(store, StubChatModel("选课时间为开学前两周【1】。"))

    done = [e for e in pipeline.ask_stream("选课什么时候开始") if e.type == "done"][-1]
    assert done.data["refused"] is False
    assert done.data["hit_ids"] == ["d:00000"]
    assert done.data["hits"][0]["source"] == "选课办法.txt"


def test_threshold_refusal_still_short_circuits_llm(tmp_path):
    """检索层拒答时不应产生任何模型输出（省 token、降延迟）。"""
    store, _ = _store_with_one_chunk(tmp_path)

    class ExplodingChat(MockChatModel):
        def stream(self, messages, **kwargs):  # pragma: no cover - 不应被调用
            raise AssertionError("检索层已拒答，不应调用大模型")

    pipeline = _pipeline_with(store, ExplodingChat(), threshold=1.01)
    events = list(pipeline.ask_stream("选课什么时候开始"))
    assert [e.type for e in events] == ["retrieval", "delta", "done"]
    assert events[-1].data["refused"] is True


# ---------------------------------------------------------------------------
# 向量维度校验
# ---------------------------------------------------------------------------
def test_upsert_rejects_mismatched_dimension(tmp_path):
    store = LocalVectorStore(root=tmp_path / "vs", dim=8)
    with pytest.raises(VectorDimensionMismatch, match="维度不一致"):
        store.upsert(
            [
                VectorRecord(
                    id="x:0",
                    doc_id="x",
                    source="a.txt",
                    text="文本",
                    vector=[0.1] * 16,
                )
            ]
        )


def test_reopening_store_with_new_dimension_raises_actionable_error(tmp_path):
    """换嵌入模型却复用旧库目录时，必须给出可操作的报错而不是 numpy 崩溃。"""
    root = tmp_path / "vs"
    first = LocalVectorStore(root=root, dim=8)
    first.upsert(
        [VectorRecord(id="x:0", doc_id="x", source="a.txt", text="文本", vector=[0.1] * 8)]
    )

    with pytest.raises(VectorDimensionMismatch) as excinfo:
        LocalVectorStore(root=root, dim=1024)
    message = str(excinfo.value)
    assert "维度不匹配" in message
    assert "EMBEDDING_DIM" in message
    assert str(root) in message


def test_reopening_store_with_same_dimension_is_fine(tmp_path):
    root = tmp_path / "vs"
    LocalVectorStore(root=root, dim=8).upsert(
        [VectorRecord(id="x:0", doc_id="x", source="a.txt", text="文本", vector=[0.1] * 8)]
    )
    reopened = LocalVectorStore(root=root, dim=8)
    assert reopened.count() == 1