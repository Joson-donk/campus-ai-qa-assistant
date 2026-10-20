"""文本分块模块（FR-A2）。

从零手写两种分块策略，不依赖 LangChain / LlamaIndex 等高层封装：

1. ``fixed``     —— 固定字符长度分块，支持 ``chunk_overlap``；
2. ``recursive`` —— 递归字符分块，分隔符优先级为
   ``\\n\\n → \\n → 。 → ！ → ？ → ； → ，``，并支持 ``chunk_overlap``。

两种策略都记录分块在原文中的字符偏移量（``char_start`` / ``char_end``），
便于评测脚本回溯定位与人工核对。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import List, Optional, Sequence, Tuple

# FR-A2：递归分块的分隔符优先级（段落 → 换行 → 中文句末 → 分号 → 逗号）
DEFAULT_SEPARATORS: Tuple[str, ...] = ("\n\n", "\n", "。", "！", "？", "；", "，")

STRATEGY_FIXED = "fixed"
STRATEGY_RECURSIVE = "recursive"
VALID_STRATEGIES = (STRATEGY_FIXED, STRATEGY_RECURSIVE)


@dataclass
class TextChunk:
    """一个文本块。"""

    text: str
    chunk_index: int = 0
    page: Optional[str] = None  # 页码或章节（对应 FR-A4 的 page 字段）
    char_start: int = 0
    char_end: int = 0
    strategy: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["length"] = len(self.text)
        return data


def normalize_text(text: str) -> str:
    """清洗文本：统一换行符、压缩空白，但保留段落结构。"""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clamp_params(max_length: int, chunk_overlap: int) -> Tuple[int, int]:
    max_length = max(1, int(max_length))
    chunk_overlap = max(0, min(int(chunk_overlap), max_length - 1))
    return max_length, chunk_overlap


# ---------------------------------------------------------------------------
# 策略一：固定字符长度分块
# ---------------------------------------------------------------------------
def split_by_length(
    text: str,
    max_length: int = 512,
    chunk_overlap: int = 64,
    page: Optional[str] = None,
) -> List[TextChunk]:
    """固定字符长度分块：窗口 ``max_length``，步长 ``max_length - chunk_overlap``。"""
    text = normalize_text(text)
    if not text:
        return []
    max_length, chunk_overlap = _clamp_params(max_length, chunk_overlap)
    step = max_length - chunk_overlap
    total = len(text)

    chunks: List[TextChunk] = []
    start = 0
    while start < total:
        end = min(start + max_length, total)
        piece = text[start:end].strip()
        if piece:
            chunks.append(
                TextChunk(
                    text=piece,
                    page=page,
                    char_start=start,
                    char_end=end,
                    strategy=STRATEGY_FIXED,
                )
            )
        if end >= total:
            break
        start += step

    for i, chunk in enumerate(chunks):
        chunk.chunk_index = i
    return chunks


# ---------------------------------------------------------------------------
# 策略二：递归字符分块
# ---------------------------------------------------------------------------
def _split_spans(text: str, base: int, sep: str) -> List[Tuple[int, int]]:
    """按 ``sep`` 切分并返回**含绝对偏移量**的片段区间（分隔符留在片段尾部）。"""
    spans: List[Tuple[int, int]] = []
    start = 0
    n = len(text)
    while True:
        idx = text.find(sep, start)
        if idx < 0:
            if start < n:
                spans.append((base + start, base + n))
            break
        end = idx + len(sep)
        if end > start:
            spans.append((base + start, base + end))
        start = end
    return spans


def _atomic_spans(
    text: str,
    base: int,
    separators: Sequence[str],
    max_length: int,
) -> List[Tuple[int, int]]:
    """递归切出长度不超过 ``max_length`` 的**原子片段**（带绝对偏移量）。

    按 ``separators`` 的优先级选择第一个在文本中真实出现的分隔符切分；
    若切出的片段仍然超长，就用下一级分隔符继续递归；分隔符用尽时按长度硬切，
    因此算法一定会收敛。
    """
    if not text.strip():
        return []
    if len(text) <= max_length:
        return [(base, base + len(text))]

    sep: Optional[str] = None
    rest: Sequence[str] = ()
    for i, candidate in enumerate(separators):
        if candidate and candidate in text:
            sep = candidate
            rest = separators[i + 1 :]
            break

    if sep is None:
        return [
            (base + i, base + min(i + max_length, len(text)))
            for i in range(0, len(text), max_length)
        ]

    out: List[Tuple[int, int]] = []
    for s, e in _split_spans(text, base, sep):
        sub = text[s - base : e - base]
        if not sub.strip():
            continue
        if len(sub) <= max_length:
            out.append((s, e))
        else:
            out.extend(_atomic_spans(sub, s, rest, max_length))
    return out


_OVERLAP_BREAK_CHARS = ("。", "！", "？", "；", "\n", "，", ".", "!", "?", ";", ",")


def _snap_to_punctuation(text: str, start: int, prev_end: int, min_overlap: int = 4) -> int:
    """把重叠起点向后对齐到最近的标点之后，避免切出半句话。

    若在可用区间内找不到标点，则保持原始的字符级重叠起点。
    """
    if start >= prev_end:
        return start
    limit = prev_end - min_overlap  # 至少保留 min_overlap 个字符的重叠
    for idx in range(start, max(start, limit)):
        if text[idx] in _OVERLAP_BREAK_CHARS:
            return idx + 1
    return start


def _merge_spans(
    text: str,
    spans: Sequence[Tuple[int, int]],
    max_length: int,
    chunk_overlap: int,
) -> List[Tuple[int, int]]:
    """贪心合并原子片段成块，并在相邻块之间制造 ``chunk_overlap`` 的重叠。

    分两步：

    1. **按片段合并**：把原子片段贪心装进一块，装满（再加一个片段就超过
       ``max_length``）就封块，保证块内不切断任何片段；
    2. **字符级重叠**：让后一块的起点向前回溯 ``chunk_overlap`` 个字符，
       并尽量对齐到标点之后。回溯范围受三重约束——不越过上一块起点、
       不让本块长度超过 ``max_length``、不越过后一块原本的起点。

    这样即使一块只装得下一个长段落，相邻块之间依然有上下文重叠。
    """
    groups: List[Tuple[int, int]] = []
    group: List[int] = []
    group_len = 0

    for i, (s, e) in enumerate(spans):
        piece_len = e - s
        if group and group_len + piece_len > max_length:
            groups.append((group[0], group[-1]))
            group, group_len = [], 0
        group.append(i)
        group_len += piece_len
    if group:
        groups.append((group[0], group[-1]))

    merged = [(spans[a][0], spans[b][1]) for a, b in groups]
    if chunk_overlap <= 0 or len(merged) < 2:
        return merged

    overlapped: List[Tuple[int, int]] = [merged[0]]
    for i in range(1, len(merged)):
        prev_start, prev_end = merged[i - 1]
        cur_start, cur_end = merged[i]
        start = max(prev_end - chunk_overlap, prev_start, cur_end - max_length)
        start = min(start, cur_start)
        start = _snap_to_punctuation(text, start, prev_end)
        overlapped.append((start, cur_end))
    return overlapped


def split_recursive(
    text: str,
    max_length: int = 512,
    chunk_overlap: int = 64,
    separators: Sequence[str] = DEFAULT_SEPARATORS,
    page: Optional[str] = None,
) -> List[TextChunk]:
    """递归字符分块（FR-A2）。"""
    text = normalize_text(text)
    if not text:
        return []
    max_length, chunk_overlap = _clamp_params(max_length, chunk_overlap)
    separators = tuple(s for s in separators if s) or DEFAULT_SEPARATORS

    spans = _atomic_spans(text, 0, separators, max_length)
    chunks: List[TextChunk] = []
    for s, e in _merge_spans(text, spans, max_length, chunk_overlap):
        piece = text[s:e].strip()
        if not piece:
            continue
        chunks.append(
            TextChunk(
                text=piece,
                page=page,
                char_start=s,
                char_end=e,
                strategy=STRATEGY_RECURSIVE,
            )
        )
    for i, chunk in enumerate(chunks):
        chunk.chunk_index = i
    return chunks


def split_text(
    text: str,
    strategy: str = STRATEGY_RECURSIVE,
    max_length: int = 512,
    chunk_overlap: int = 64,
    separators: Sequence[str] = DEFAULT_SEPARATORS,
    page: Optional[str] = None,
) -> List[TextChunk]:
    """统一入口：按 ``strategy`` 选择分块策略，非法策略直接抛 ``ValueError``。"""
    strategy = (strategy or STRATEGY_RECURSIVE).strip().lower()
    aliases = {
        "length": STRATEGY_FIXED,
        "char": STRATEGY_FIXED,
        "chars": STRATEGY_FIXED,
        "fixed_length": STRATEGY_FIXED,
        "rec": STRATEGY_RECURSIVE,
        "recursion": STRATEGY_RECURSIVE,
        "recursive_split": STRATEGY_RECURSIVE,
    }
    strategy = aliases.get(strategy, strategy)
    if strategy not in VALID_STRATEGIES:
        raise ValueError(
            f"不支持的分块策略: {strategy!r}，可选值: {list(VALID_STRATEGIES)}"
        )
    if strategy == STRATEGY_FIXED:
        return split_by_length(text, max_length, chunk_overlap, page)
    return split_recursive(text, max_length, chunk_overlap, separators, page)