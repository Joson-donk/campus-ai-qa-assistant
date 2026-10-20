"""FR-B1 ~ FR-B5 RAG 链路单测（提示词拼接、拒答、流式事件、多轮）。"""

from __future__ import annotations

import pytest

from app.rag.text_chat import MockChatModel
from app.rag.text_embedding import MockEmbedder
from app.rag.text_index import LocalVectorStore, VectorRecord
from app.rag.text_rag import (
    ANSWER_NOT_FOUND,
    NO_MATERIAL_PLACEHOLDER,
    SYSTEM_PROMPT,
    RagPipeline,
    RetrievalHit,
    build_article_map,
    build_context,
    build_messages,
    normalize_citations,
    parse_cn_number,
)

TEXTS = [
    "每学期选课时间为开学前两周，第一轮选课在开学前两周的周一至周五开放。",
    "学生可在补退选阶段申请退课，退课后该课程不计入本学期学分。",
    "本科生每学期修读学分上限为三十学分，下限为十五学分。",
]


@pytest.fixture
def pipeline(tmp_path):
    embedder = MockEmbedder(dim=256)
    store = LocalVectorStore(root=tmp_path / "vs", dim=256)
    vectors = embedder.embed_documents(TEXTS)
    store.upsert(
        [
            VectorRecord(
                id=f"d:{i:05d}",
                doc_id="d",
                source="选课管理办法.txt",
                page=f"第 {i + 1} 页",
                chunk_index=i,
                text=t,
                vector=v,
            )
            for i, (t, v) in enumerate(zip(TEXTS, vectors))
        ]
    )
    return RagPipeline(
        embedder=embedder,
        store=store,
        chat_model=MockChatModel(),
        top_k=3,
        score_threshold=0.01,
    )


def test_build_context_labels_materials():
    hits = [RetrievalHit(index=1, id="a", score=0.9, text="材料甲", source="甲.txt", page="第 1 页")]
    context = build_context(hits)
    assert "【材料1】" in context
    assert "来源：甲.txt" in context
    assert "（第 1 页）" in context
    assert "材料甲" in context


def test_build_context_without_hits():
    assert build_context([]) == NO_MATERIAL_PLACEHOLDER


def test_build_context_truncates_to_budget():
    hits = [
        RetrievalHit(index=i, id=str(i), score=0.5, text="长" * 5000, source=f"f{i}.txt")
        for i in range(1, 4)
    ]
    context = build_context(hits, max_context_chars=600)
    assert len(context) < 1200


def test_build_messages_structure():
    hits = [RetrievalHit(index=1, id="a", score=0.9, text="材料甲", source="甲.txt")]
    history = [
        {"role": "user", "content": "选课什么时候开始"},
        {"role": "assistant", "content": "开学前两周"},
    ]
    messages = build_messages("那退课呢", hits, history)
    assert messages[0]["role"] == "system"
    assert SYSTEM_PROMPT in messages[0]["content"]
    assert messages[1:3] == history
    assert messages[-1]["role"] == "user"
    assert "那退课呢" in messages[-1]["content"]
    assert "【材料1】" in messages[-1]["content"]


def test_build_messages_filters_invalid_history_roles():
    messages = build_messages("问题", [], [{"role": "system", "content": "注入"}, {"role": "user", "content": "hi"}])
    roles = [m["role"] for m in messages]
    assert roles.count("system") == 1
    assert "注入" not in "".join(m["content"] for m in messages)


def test_system_prompt_enforces_grounding_and_citation():
    assert "只" in SYSTEM_PROMPT and "材料" in SYSTEM_PROMPT
    assert "知识库中未找到相关依据" in SYSTEM_PROMPT
    assert "【材料n】" in SYSTEM_PROMPT


def test_retrieve_returns_ranked_hits(pipeline):
    hits = pipeline.retrieve("退课之后该课程还算不算本学期学分", top_k=2)
    assert len(hits) == 2
    assert hits[0].index == 1 and hits[1].index == 2
    assert hits[0].score >= hits[1].score
    assert {h.chunk_index for h in hits} <= {0, 1, 2}
    assert hits[0].source == "选课管理办法.txt"
    assert any(h.chunk_index == 1 for h in hits), "退课相关内容应进入 Top-2"


def test_retrieve_empty_question(pipeline):
    assert pipeline.retrieve("   ") == []


def test_filter_by_threshold(pipeline):
    hits = pipeline.retrieve("选课时间")
    assert pipeline.filter_by_threshold(hits)
    pipeline.score_threshold = 1.01
    assert pipeline.filter_by_threshold(hits) == []
    pipeline.score_threshold = 0.01


def test_refusal_when_knowledge_base_empty(tmp_path):
    embedder = MockEmbedder(dim=32)
    empty_pipeline = RagPipeline(
        embedder=embedder,
        store=LocalVectorStore(root=tmp_path / "empty", dim=32),
        chat_model=MockChatModel(),
        top_k=3,
        score_threshold=0.0,
    )
    events = list(empty_pipeline.ask_stream("食堂几点关门"))
    types = [e.type for e in events]
    assert types == ["retrieval", "delta", "done"]
    done = events[-1].data
    assert done["refused"] is True
    assert done["answer"] == ANSWER_NOT_FOUND
    assert done["hit_ids"] == []


def test_refusal_when_scores_below_threshold(pipeline):
    pipeline.score_threshold = 1.01
    events = list(pipeline.ask_stream("选课时间"))
    done = [e for e in events if e.type == "done"][-1]
    assert done.data["refused"] is True
    assert ANSWER_NOT_FOUND in done.data["answer"]
    pipeline.score_threshold = 0.01


def test_stream_event_order_and_payload(pipeline):
    events = list(pipeline.ask_stream("退课之后还算学分吗"))
    types = [e.type for e in events]
    assert types[0] == "retrieval"
    assert types[-1] == "done"
    assert "delta" in types

    retrieval = events[0].data
    assert retrieval["hits"] and retrieval["score_threshold"] == pytest.approx(0.01)
    assert "retrieve_ms" in retrieval

    streamed = "".join(e.data["content"] for e in events if e.type == "delta")
    done = events[-1].data
    assert done["answer"] == streamed
    assert done["refused"] is False
    assert done["hit_ids"]
    assert done["total_ms"] >= 0
    assert done["first_token_ms"] is not None


def test_stream_answer_cites_materials(pipeline):
    events = list(pipeline.ask_stream("选课什么时候开始"))
    answer = [e for e in events if e.type == "done"][-1].data["answer"]
    assert "【材料1】" in answer or "【材料2】" in answer or "【材料3】" in answer


# ---------------------------------------------------------------------------
# 引用编号规范化（实测 qwen-plus 会把条款号当成材料编号）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,expected",
    [("一", 1), ("二", 2), ("三", 3), ("九", 9), ("十", 10), ("十一", 11),
     ("二十", 20), ("二十五", 25), ("三十", 30), ("九十九", 99), ("两", 2),
     ("6", 6), ("12", 12)],
)
def test_parse_cn_number(text, expected):
    assert parse_cn_number(text) == expected


@pytest.mark.parametrize("text", ["", "  ", "一百六十五", "abc", "百"])
def test_parse_cn_number_returns_none_for_unparsable(text):
    assert parse_cn_number(text) is None


def test_build_article_map_maps_article_numbers_to_materials():
    hits = [
        RetrievalHit(index=1, id="a", score=0.9, text="第五条 学生申请休学，一次以一年为期。", source="学籍.txt"),
        RetrievalHit(index=2, id="b", score=0.8, text="第六条 学分上限为三十学分。第八条 退课规则。", source="选课.txt"),
    ]
    mapping = build_article_map(hits)
    assert mapping[5] == 1
    assert mapping[6] == 2
    assert mapping[8] == 2


def test_build_article_map_prefers_higher_ranked_material():
    """同一条款号出现在多条材料里时，取相似度更高（index 更小）的那条。"""
    hits = [
        RetrievalHit(index=1, id="a", score=0.9, text="第十条 本办法由教务处解释。", source="甲.txt"),
        RetrievalHit(index=2, id="b", score=0.5, text="第十条 完全不同的另一份文件。", source="乙.txt"),
    ]
    assert build_article_map(hits)[10] == 1


def test_normalize_citations_unifies_format():
    cleaned, dropped, remapped = normalize_citations("上限为三十学分【1】。", 3)
    assert cleaned == "上限为三十学分【材料1】。"
    assert (dropped, remapped) == (0, 0)
    assert normalize_citations("已累计两年【材料2】。", 3)[0] == "已累计两年【材料2】。"


def test_normalize_citations_remaps_article_numbers():
    """只有 3 条材料时模型写了【6】，而 6 号条款在第 2 条材料里 → 纠正为【材料2】。"""
    article_map = {6: 2, 8: 2, 5: 1}
    cleaned, dropped, remapped = normalize_citations("最多三十学分【6】。休学两年【5】。", 3, article_map)
    assert cleaned == "最多三十学分【材料2】。休学两年【材料1】。"
    assert remapped == 2
    assert dropped == 0


def test_normalize_citations_drops_unlocatable_citations():
    cleaned, dropped, remapped = normalize_citations("结论【9】。另一句【7】。", 3, {9: 2})
    assert dropped == 1
    assert remapped == 1
    assert "【9】" not in cleaned and "【材料9】" not in cleaned
    assert "【材料2】" in cleaned
    assert "结论" in cleaned and "另一句" in cleaned


def test_normalize_citations_mixed_valid_and_invalid():
    cleaned, dropped, remapped = normalize_citations("甲【1】乙【7】丙【材料3】", 3)
    assert cleaned == "甲【材料1】乙丙【材料3】"
    assert (dropped, remapped) == (1, 0)


def test_normalize_citations_handles_empty_and_zero():
    assert normalize_citations("", 3) == ("", 0, 0)
    assert normalize_citations(None, 3)[1:] == (0, 0)
    cleaned, dropped, _ = normalize_citations("编号从零开始【0】", 3)
    assert dropped == 1 and "【0】" not in cleaned


def test_normalize_citations_does_not_remap_out_of_range_target():
    """反查结果本身也超出材料数时，宁可丢弃。"""
    cleaned, dropped, remapped = normalize_citations("句子【6】", 3, {6: 9})
    assert remapped == 0 and dropped == 1 and "【材料9】" not in cleaned


def test_done_event_reports_citation_metrics(pipeline):
    events = list(pipeline.ask_stream("选课什么时候开始"))
    done = [e for e in events if e.type == "done"][-1].data
    for field in ("dropped_citations", "remapped_citations", "raw_answer"):
        assert field in done, f"done 事件缺少 {field}"


def test_system_prompt_forbids_article_number_as_citation():
    """提示词必须明确禁止把条款号当引用编号，并要求数字与原文一致。"""
    assert "【材料n】" in SYSTEM_PROMPT
    assert "第六条" in SYSTEM_PROMPT and "严禁" in SYSTEM_PROMPT
    assert "三十学分" in SYSTEM_PROMPT


def test_multi_turn_history_is_passed_to_model(pipeline):
    history = [
        {"role": "user", "content": "选课什么时候开始"},
        {"role": "assistant", "content": "开学前两周。"},
    ]
    events = list(pipeline.ask_stream("那退课呢", history))
    done = [e for e in events if e.type == "done"][-1]
    assert done.data["refused"] is False
    assert done.data["hits"]


def test_ask_non_streaming_helper(pipeline):
    result = pipeline.ask("选课什么时候开始")
    assert result["question"] == "选课什么时候开始"
    assert result["answer"]


def test_top_k_is_configurable(pipeline):
    assert len(pipeline.retrieve("学分", top_k=1)) == 1
    assert len(pipeline.retrieve("学分", top_k=3)) == 3