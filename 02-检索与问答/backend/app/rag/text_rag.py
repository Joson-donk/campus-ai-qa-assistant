"""Naive RAG 编排（FR-B1 ~ FR-B5）。

把「向量化问题 → 余弦 Top-K 检索 → 提示词拼接 → 流式生成」串成一条链路，
全部手写，不依赖 LangChain 的 Chain / Retriever 抽象。

关键约束：

* **FR-B3**：提示词强制模型只依据材料回答、标注引用编号【1】【2】，
  找不到依据时明确说「知识库中未找到相关依据」；
* **拒答兜底**：检索最高分低于 ``score_threshold`` 时**根本不调用大模型**，
  直接返回拒答文案 —— 从机制上杜绝编造，同时省 token、降延迟；
* **FR-B5**：以 ``messages`` 形式维护多轮历史，可理解「那退课呢？」这类追问。
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Sequence

from .text_chat import BaseChatModel, ChatModelError, Message
from .text_index import BaseVectorStore, Hit

logger = logging.getLogger(__name__)

ANSWER_NOT_FOUND = "知识库中未找到相关依据，无法给出有出处的回答。建议补充相关政策文档后再试。"

# 模型自己表达「无依据」时的常见措辞，用于识别模型层面的拒答
REFUSAL_PHRASES = (
    "知识库中未找到相关依据",
    "未找到相关依据",
    "没有找到相关依据",
    "未找到相关",
    "材料中未",
    "材料中没有",
    "上述材料未",
    "无法从材料中",
    "无法依据材料",
    "根据现有材料无法",
)


def looks_like_refusal(answer: str) -> bool:
    """判断答案是否是「拒答」。

    拒答有两条来源，任一条成立即算：

    1. **检索层**：Top-K 最高相似度低于阈值 → 直接不调用大模型（见 ``ask_stream``）；
    2. **模型层**：材料过了阈值但与问题实际无关，模型遵守提示词约束自行拒答。

    第 2 条同样必须被识别，否则日志里的 ``refused`` 字段会失真，
    前端也无法正确展示「未找到依据」这一态。
    """
    if not answer:
        return False
    text = answer.strip()
    return any(phrase in text for phrase in REFUSAL_PHRASES)

SYSTEM_PROMPT = """你是山西大学的校园政策答疑助手，服务对象是在校学生。
你只能依据下面【材料】中给出的政策原文回答问题，必须严格遵守：

1. 只使用材料中的信息作答。禁止使用你自己的常识、猜测或编造任何数字、学分、时限、条件。
2. 材料中找不到答案，或材料与问题无关时，必须原样回答：知识库中未找到相关依据。
3. 每当你使用某条材料的内容，就在该句末尾标注材料编号，格式严格写作【材料n】，
   其中 n 是该材料在下方【材料】区块中的序号（从 1 开始，最大不超过材料总条数）。
   严禁把政策条款号当成引用编号：例如材料里出现「第六条」「第八条」，
   你应当标注的是【材料1】这类材料序号，绝不能写成【6】【8】。
   也严禁编造不存在的材料序号。
4. 涉及学分、金额、时间、期限、百分比等关键信息时，必须与材料原文**用词完全一致**：
   原文写「三十学分」就写「三十学分」，不得改写成「30 学分」；
   原文写「八千元」就写「八千元」，不得改写成「8000 元」。
5. 用简体中文回答，先给结论，再列依据，条理清晰，不要输出与问题无关的客套话。
6. 如果用户的追问依赖上文，请结合对话历史理解其真实意图后再作答。"""

USER_PROMPT_TEMPLATE = """【材料】
{context}

【问题】
{question}

请严格依据上述材料回答，并按要求标注引用编号【材料n】（n 为材料序号，不是条款号）。"""

NO_MATERIAL_PLACEHOLDER = "（无相关材料）"

# 同时兼容【材料3】与【3】两种写法（不同模型的遵守程度不同）
CITATION_RE = re.compile(r"【\s*(?:材料)?\s*(\d{1,3})\s*】")

# 政策文本里的条款号：第六条 / 第三章 / 第二款
ARTICLE_RE = re.compile(r"第\s*([零一二两三四五六七八九十百\d]{1,4})\s*[条章节款项]")

_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def parse_cn_number(text: str) -> int | None:
    """把中文数字（1~99）或阿拉伯数字解析成 int，解析不了返回 None。"""
    text = (text or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if "十" in text:
        head, _, tail = text.partition("十")
        if head and head not in _CN_DIGITS:
            return None
        if tail and (len(tail) != 1 or tail not in _CN_DIGITS):
            return None
        tens = _CN_DIGITS.get(head, 1) if head else 1
        ones = _CN_DIGITS[tail] if tail else 0
        return tens * 10 + ones
    if len(text) == 1 and text in _CN_DIGITS:
        return _CN_DIGITS[text]
    return None


def build_article_map(hits: Sequence[RetrievalHit]) -> Dict[int, int]:
    """建立「条款号 → 材料序号」的映射。

    实测 qwen-plus 即使被明确要求，也倾向把政策原文里的**条款号**当成引用编号
    （只有 3 条材料时输出【6】【8】）。与其直接丢弃这些标注，不如反查：
    如果编号 6 恰好对应某条材料里的「第六条」，就把它改写成该材料的正确序号。
    同一个条款号出现在多条材料里时取**靠前**的那条（相似度更高）。
    """
    mapping: Dict[int, int] = {}
    for hit in sorted(hits, key=lambda h: h.index):
        for match in ARTICLE_RE.finditer(hit.text or ""):
            number = parse_cn_number(match.group(1))
            if number and number not in mapping:
                mapping[number] = hit.index
    return mapping


def normalize_citations(
    answer: str,
    material_count: int,
    article_map: Dict[int, int] | None = None,
) -> tuple[str, int, int]:
    """规范化答案中的引用编号。

    返回 ``(处理后的答案, 被剔除的悬空引用数, 由条款号纠正的引用数)``：

    * 编号在 ``1 ~ material_count`` 之间 → 统一改写为 ``【材料n】``；
    * 超出范围但能在 ``article_map`` 里反查到 → **纠正**为正确的材料序号；
    * 既超范围又反查不到 → 删除该标记（宁可少一个标注，也不给错误出处）。
    """
    if not answer:
        return answer or "", 0, 0

    dropped = 0
    remapped = 0
    article_map = article_map or {}

    def replace(match: re.Match) -> str:
        nonlocal dropped, remapped
        number = int(match.group(1))
        if 1 <= number <= material_count:
            return f"【材料{number}】"
        target = article_map.get(number)
        if target and 1 <= target <= material_count:
            remapped += 1
            return f"【材料{target}】"
        dropped += 1
        return ""

    cleaned = CITATION_RE.sub(replace, answer)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([。，；：])", r"\1", cleaned)
    return cleaned, dropped, remapped


@dataclass
class RetrievalHit:
    """对外暴露的检索命中结果（FR-B4）。"""

    index: int
    id: str
    score: float
    text: str
    source: str
    page: Optional[str] = None
    doc_id: Optional[str] = None
    chunk_index: int = 0

    @classmethod
    def from_hit(cls, hit: Hit, index: int) -> "RetrievalHit":
        return cls(
            index=index,
            id=hit.id,
            score=round(float(hit.score), 6),
            text=hit.text,
            source=hit.source,
            page=hit.page,
            doc_id=hit.doc_id,
            chunk_index=hit.chunk_index,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "id": self.id,
            "score": self.score,
            "text": self.text,
            "source": self.source,
            "page": self.page,
            "doc_id": self.doc_id,
            "chunk_index": self.chunk_index,
        }


@dataclass
class RagEvent:
    """流式事件。``type`` 取值：``retrieval`` / ``delta`` / ``done`` / ``error``。"""

    type: str
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "data": self.data}


def build_context(hits: Sequence[RetrievalHit], max_context_chars: int = 6000) -> str:
    """把命中片段拼成提示词里的【材料】区块（FR-B3）。"""
    if not hits:
        return NO_MATERIAL_PLACEHOLDER
    blocks: List[str] = []
    used = 0
    for hit in hits:
        header = f"【材料{hit.index}】来源：{hit.source}"
        if hit.page:
            header += f"（{hit.page}）"
        text = hit.text.strip()
        room = max_context_chars - used - len(header)
        if room <= 80:
            break
        if len(text) > room:
            text = text[:room] + "…"
        block = f"{header}\n{text}"
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks) if blocks else NO_MATERIAL_PLACEHOLDER


def build_messages(
    question: str,
    hits: Sequence[RetrievalHit],
    history: Optional[Sequence[Message]] = None,
    max_context_chars: int = 6000,
    max_history_messages: int = 6,
) -> List[Message]:
    """拼接最终发给大模型的 ``messages``（FR-B2 / FR-B5）。"""
    messages: List[Message] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        trimmed = [m for m in history if m.get("role") in ("user", "assistant") and m.get("content")]
        messages.extend(trimmed[-max_history_messages:])
    messages.append(
        {
            "role": "user",
            "content": USER_PROMPT_TEMPLATE.format(
                context=build_context(hits, max_context_chars), question=question.strip()
            ),
        }
    )
    return messages


class RagPipeline:
    """检索 + 生成的编排器。"""

    def __init__(
        self,
        embedder,
        store: BaseVectorStore,
        chat_model: BaseChatModel,
        top_k: int = 3,
        score_threshold: float = 0.30,
        max_context_chars: int = 6000,
        max_history_messages: int = 6,
    ) -> None:
        self.embedder = embedder
        self.store = store
        self.chat_model = chat_model
        self.top_k = max(1, int(top_k))
        self.score_threshold = float(score_threshold)
        self.max_context_chars = int(max_context_chars)
        self.max_history_messages = int(max_history_messages)

    # -- 检索 -----------------------------------------------------------
    def retrieve(self, question: str, top_k: Optional[int] = None) -> List[RetrievalHit]:
        """FR-B1：问题向量化 + 余弦相似度 Top-K。"""
        question = (question or "").strip()
        if not question:
            return []
        k = max(1, int(top_k or self.top_k))
        query_vector = self.embedder.embed_query(question)
        hits = self.store.search(query_vector, top_k=k)
        return [RetrievalHit.from_hit(hit, i) for i, hit in enumerate(hits, start=1)]

    def filter_by_threshold(self, hits: Sequence[RetrievalHit]) -> List[RetrievalHit]:
        """过滤低分命中，作为「拒答」判定依据。"""
        return [h for h in hits if h.score >= self.score_threshold]

    # -- 非流式 ---------------------------------------------------------
    def ask(
        self,
        question: str,
        history: Optional[Sequence[Message]] = None,
        top_k: Optional[int] = None,
    ) -> Dict[str, Any]:
        answer = "".join(
            event.data.get("content", "")
            for event in self.ask_stream(question, history, top_k)
            if event.type == "delta"
        )
        return {"question": question, "answer": answer}

    # -- 流式（FR-B2） --------------------------------------------------
    def ask_stream(
        self,
        question: str,
        history: Optional[Sequence[Message]] = None,
        top_k: Optional[int] = None,
    ) -> Iterator[RagEvent]:
        started = time.perf_counter()
        question = (question or "").strip()
        if not question:
            yield RagEvent("error", {"message": "问题不能为空"})
            return

        try:
            raw_hits = self.retrieve(question, top_k)
        except Exception as exc:  # noqa: BLE001
            logger.exception("检索失败")
            yield RagEvent("error", {"message": f"检索失败: {exc}"})
            return

        hits = self.filter_by_threshold(raw_hits)
        retrieve_ms = int((time.perf_counter() - started) * 1000)

        yield RagEvent(
            "retrieval",
            {
                "hits": [h.to_dict() for h in raw_hits],
                "used": [h.to_dict() for h in hits],
                "score_threshold": self.score_threshold,
                "retrieve_ms": retrieve_ms,
            },
        )

        # 兜底拒答：没有达标材料就不调用大模型，避免编造
        if not hits:
            yield RagEvent("delta", {"content": ANSWER_NOT_FOUND})
            yield RagEvent(
                "done",
                {
                    "answer": ANSWER_NOT_FOUND,
                    "hit_ids": [],
                    "hits": [h.to_dict() for h in raw_hits],
                    "refused": True,
                    "retrieve_ms": retrieve_ms,
                    "total_ms": int((time.perf_counter() - started) * 1000),
                    "model": getattr(self.chat_model, "model", ""),
                },
            )
            return

        messages = build_messages(
            question,
            hits,
            history,
            self.max_context_chars,
            self.max_history_messages,
        )

        parts: List[str] = []
        first_token_ms: Optional[int] = None
        try:
            for piece in self.chat_model.stream(messages):
                if not piece:
                    continue
                if first_token_ms is None:
                    first_token_ms = int((time.perf_counter() - started) * 1000)
                parts.append(piece)
                yield RagEvent("delta", {"content": piece})
        except ChatModelError as exc:
            logger.exception("对话模型调用失败")
            yield RagEvent("error", {"message": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("流式生成异常")
            yield RagEvent("error", {"message": f"生成失败: {exc}"})
            return

        raw_answer = "".join(parts).strip() or ANSWER_NOT_FOUND
        answer, dropped_citations, remapped_citations = normalize_citations(
            raw_answer, len(hits), build_article_map(hits)
        )
        if dropped_citations:
            logger.warning(
                "模型输出了 %s 个无法定位的引用编号，已剔除（材料数=%s）",
                dropped_citations,
                len(hits),
            )
        if remapped_citations:
            logger.info("已把 %s 个条款号引用纠正为材料序号", remapped_citations)
        refused = looks_like_refusal(answer)
        yield RagEvent(
            "done",
            {
                "answer": answer,
                "raw_answer": raw_answer,
                "dropped_citations": dropped_citations,
                "remapped_citations": remapped_citations,
                "hit_ids": [] if refused else [h.id for h in hits],
                "hits": [] if refused else [h.to_dict() for h in hits],
                "refused": refused,
                "retrieve_ms": retrieve_ms,
                "first_token_ms": first_token_ms,
                "total_ms": int((time.perf_counter() - started) * 1000),
                "model": getattr(self.chat_model, "model", ""),
            },
        )