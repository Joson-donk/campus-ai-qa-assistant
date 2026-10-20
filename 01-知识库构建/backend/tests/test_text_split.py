"""FR-A2 分块策略单测。"""

from __future__ import annotations

import pytest

from app.rag.text_split import (
    DEFAULT_SEPARATORS,
    normalize_text,
    split_by_length,
    split_recursive,
    split_text,
)

PARA = (
    "第一条 选课时间。每学期选课分两轮进行，第一轮为开学前两周。\n\n"
    "第二条 退课规则。学生可在补退选阶段申请退课，退课后不计入学分。\n\n"
    "第三条 学分上限。本科生每学期修读学分上限为三十学分，下限为十五学分。"
)


def test_normalize_text_compresses_whitespace():
    raw = "甲\r\n\r\n\r\n乙\u3000\u3000丙   丁"
    assert normalize_text(raw) == "甲\n\n乙 丙 丁"


def test_empty_text_returns_no_chunks():
    assert split_by_length("") == []
    assert split_recursive("   \n  ") == []


def test_fixed_length_respects_max_length():
    text = "字" * 1000
    chunks = split_by_length(text, max_length=100, chunk_overlap=0)
    assert len(chunks) == 10
    assert all(len(c.text) <= 100 for c in chunks)
    assert [c.chunk_index for c in chunks] == list(range(10))
    assert all(c.strategy == "fixed" for c in chunks)


def test_fixed_length_overlap_creates_shared_text():
    text = "".join(str(i % 10) for i in range(200))
    chunks = split_by_length(text, max_length=50, chunk_overlap=10)
    assert len(chunks) >= 4
    # 步长 = 50 - 10 = 40，第二块应从第 40 个字符开始
    assert chunks[1].char_start == 40
    assert chunks[0].text[-10:] == chunks[1].text[:10]


def test_fixed_length_covers_whole_text():
    text = normalize_text(PARA)
    chunks = split_by_length(text, max_length=40, chunk_overlap=0)
    rebuilt = "".join(c.text for c in chunks)
    assert rebuilt.replace(" ", "") == text.replace(" ", "")


def test_recursive_keeps_sentence_intact():
    chunks = split_recursive(PARA, max_length=60, chunk_overlap=0)
    assert chunks, "递归分块不应返回空"
    for chunk in chunks:
        assert len(chunk.text) <= 60
    # 段落边界应被优先使用：至少有一块以「第一条」开头
    assert any(c.text.startswith("第一条") for c in chunks)
    assert all(c.strategy == "recursive" for c in chunks)


def _overlap_len(a: str, b: str, limit: int = 40) -> int:
    """a 的尾部与 b 的头部的最长公共长度。"""
    best = 0
    for n in range(1, min(limit, len(a), len(b)) + 1):
        if a[-n:] == b[:n]:
            best = n
    return best


def test_recursive_uses_overlap_between_neighbours():
    chunks = split_recursive(PARA, max_length=60, chunk_overlap=20)
    assert len(chunks) >= 2
    overlaps = [_overlap_len(chunks[i].text, chunks[i + 1].text) for i in range(len(chunks) - 1)]
    assert max(overlaps) >= 4, f"相邻块之间应有字符级重叠，实际: {overlaps}"


def test_recursive_overlap_still_respects_max_length():
    chunks = split_recursive(PARA * 4, max_length=80, chunk_overlap=30)
    assert len(chunks) >= 3
    assert all(len(c.text) <= 80 for c in chunks)
    assert max(
        _overlap_len(chunks[i].text, chunks[i + 1].text) for i in range(len(chunks) - 1)
    ) >= 4


def test_recursive_without_overlap_has_no_shared_tail():
    chunks = split_recursive(PARA * 3, max_length=80, chunk_overlap=0)
    assert all(
        _overlap_len(chunks[i].text, chunks[i + 1].text) == 0 for i in range(len(chunks) - 1)
    )


def test_recursive_hard_cuts_when_no_separator():
    text = "甲" * 500
    chunks = split_recursive(text, max_length=100, chunk_overlap=0)
    assert len(chunks) == 5
    assert all(len(c.text) <= 100 for c in chunks)


def test_recursive_respects_separator_priority():
    """段落分隔符优先级最高：max_length 足够时不应把两个段落并进一块。"""
    chunks = split_recursive(PARA, max_length=60, chunk_overlap=0)
    joined = [c for c in chunks if "第一条" in c.text and "第二条" in c.text]
    assert not joined, "段落边界未被优先使用"


def test_split_text_dispatches_strategy():
    assert all(c.strategy == "fixed" for c in split_text(PARA, "fixed", 50, 0))
    assert all(c.strategy == "recursive" for c in split_text(PARA, "recursive", 50, 0))
    # 别名
    assert split_text(PARA, "length", 50, 0)[0].strategy == "fixed"
    assert split_text(PARA, "rec", 50, 0)[0].strategy == "recursive"


def test_split_text_rejects_unknown_strategy():
    with pytest.raises(ValueError, match="不支持的分块策略"):
        split_text(PARA, "semantic", 50, 0)


def test_overlap_clamped_below_max_length():
    chunks = split_by_length("字" * 300, max_length=50, chunk_overlap=999)
    assert all(len(c.text) <= 50 for c in chunks)


def test_default_separators_order():
    assert DEFAULT_SEPARATORS == ("\n\n", "\n", "。", "！", "？", "；", "，")


def test_page_label_propagated():
    chunks = split_recursive(PARA, max_length=60, chunk_overlap=0, page="第 3 页")
    assert all(c.page == "第 3 页" for c in chunks)
    assert chunks[0].to_dict()["length"] == len(chunks[0].text)