"""问答服务（模块 B + 模块 D）。

负责：会话 ID 生成 → 调 RAG 链路 → 把每次问答写入 MySQL 日志（FR-D1）。

注意：流式响应里**不使用** FastAPI 的 ``Depends(get_db)``。
FastAPI 0.106+ 会在响应发送前退出依赖，导致生成器里拿到已关闭的 Session；
因此这里统一在写日志时用 ``session_scope()`` 开一个短事务。
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, Iterator, List, Optional

from ..config import Settings
from ..db import repository
from ..db.session import session_scope
from ..exceptions import UpstreamError
from ..rag.text_rag import RagEvent, RagPipeline
from ..schemas import ChatRequest

logger = logging.getLogger(__name__)


def new_session_id() -> str:
    return uuid.uuid4().hex


class QAService:
    def __init__(self, pipeline: RagPipeline, settings: Settings) -> None:
        self.pipeline = pipeline
        self.settings = settings

    # -- 日志留痕（FR-D1） ----------------------------------------------
    def write_log(
        self,
        *,
        session_id: str,
        question: str,
        answer: str,
        hit_ids: List[str],
        top_score: float,
        refused: bool,
        retrieve_ms: int,
        first_token_ms: Optional[int],
        total_ms: int,
        model: str,
    ) -> Optional[int]:
        try:
            with session_scope() as session:
                log = repository.create_qa_log(
                    session,
                    session_id=session_id,
                    question=question,
                    answer=answer,
                    hit_ids=hit_ids,
                    hit_count=len(hit_ids),
                    top_score=top_score,
                    refused=refused,
                    retrieve_ms=retrieve_ms,
                    first_token_ms=first_token_ms,
                    total_ms=total_ms,
                    model=model,
                    strategy=self.settings.chunk_strategy,
                )
                return log.id
        except Exception:  # noqa: BLE001
            # 日志写失败不应影响用户拿到答案，只记服务端日志
            logger.exception("写入问答日志失败（不影响本次回答）")
            return None

    # -- 流式问答（FR-B2） ----------------------------------------------
    def chat_stream(self, request: ChatRequest) -> Iterator[Dict[str, Any]]:
        """产出可直接塞进 SSE 的事件字典。"""
        session_id = (request.session_id or "").strip() or new_session_id()
        history = [m.model_dump() for m in request.history]

        collected: List[str] = []
        raw_hits: List[Dict[str, Any]] = []
        used_hits: List[Dict[str, Any]] = []
        threshold = self.pipeline.score_threshold
        retrieve_ms = 0
        first_token_ms: Optional[int] = None
        total_ms = 0
        refused = False
        model_name = getattr(self.pipeline.chat_model, "model", "")
        error_message: Optional[str] = None
        started = time.perf_counter()

        for event in self.pipeline.ask_stream(request.question, history, request.top_k):
            payload: Dict[str, Any] = {"type": event.type, "session_id": session_id}

            if event.type == "retrieval":
                raw_hits = event.data.get("hits", [])
                used_hits = event.data.get("used", [])
                threshold = float(event.data.get("score_threshold", threshold))
                retrieve_ms = int(event.data.get("retrieve_ms", 0))
                payload.update(
                    {
                        "raw_hits": raw_hits,
                        "hits": used_hits,
                        "score_threshold": threshold,
                        "timing": {"retrieve_ms": retrieve_ms},
                    }
                )
            elif event.type == "delta":
                piece = event.data.get("content", "")
                collected.append(piece)
                payload["content"] = piece
            elif event.type == "done":
                refused = bool(event.data.get("refused", False))
                first_token_ms = event.data.get("first_token_ms")
                total_ms = int(event.data.get("total_ms", 0))
                model_name = event.data.get("model", model_name) or model_name
                used_hits = event.data.get("hits", used_hits)
                log_id = self.write_log(
                    session_id=session_id,
                    question=request.question,
                    answer=event.data.get("answer", ""),
                    hit_ids=[h["id"] for h in used_hits],
                    top_score=max((h.get("score", 0.0) for h in used_hits), default=0.0),
                    refused=refused,
                    retrieve_ms=retrieve_ms,
                    first_token_ms=first_token_ms,
                    total_ms=total_ms,
                    model=model_name,
                )
                payload.update(
                    {
                        "answer": event.data.get("answer", ""),
                        "raw_answer": event.data.get("raw_answer", ""),
                        "dropped_citations": event.data.get("dropped_citations", 0),
                    "remapped_citations": event.data.get("remapped_citations", 0),
                        "remapped_citations": event.data.get("remapped_citations", 0),
                        "hits": used_hits,
                        "refused": refused,
                        "model": model_name,
                        "log_id": log_id,
                        "timing": {
                            "retrieve_ms": retrieve_ms,
                            "first_token_ms": first_token_ms,
                            "total_ms": total_ms,
                        },
                    }
                )
            elif event.type == "error":
                error_message = event.data.get("message", "未知错误")
                payload["message"] = error_message

            yield payload

        if error_message is not None:
            total_ms = int((time.perf_counter() - started) * 1000)
            self.write_log(
                session_id=session_id,
                question=request.question,
                answer=f"[生成失败] {error_message}",
                hit_ids=[h["id"] for h in used_hits],
                top_score=max((h.get("score", 0.0) for h in used_hits), default=0.0),
                refused=False,
                retrieve_ms=retrieve_ms,
                first_token_ms=first_token_ms,
                total_ms=total_ms,
                model=model_name,
            )

    # -- 非流式问答（便于 Swagger 自测） --------------------------------
    def chat_once(self, request: ChatRequest) -> Dict[str, Any]:
        session_id = (request.session_id or "").strip() or new_session_id()
        history = [m.model_dump() for m in request.history]

        raw_hits: List[Dict[str, Any]] = []
        used_hits: List[Dict[str, Any]] = []
        threshold = self.pipeline.score_threshold
        answer_parts: List[str] = []
        retrieve_ms = 0
        first_token_ms: Optional[int] = None
        total_ms = 0
        refused = False
        model_name = getattr(self.pipeline.chat_model, "model", "")
        error_message: Optional[str] = None

        for event in self.pipeline.ask_stream(request.question, history, request.top_k):
            if event.type == "retrieval":
                raw_hits = event.data.get("hits", [])
                used_hits = event.data.get("used", [])
                threshold = float(event.data.get("score_threshold", threshold))
                retrieve_ms = int(event.data.get("retrieve_ms", 0))
            elif event.type == "delta":
                answer_parts.append(event.data.get("content", ""))
            elif event.type == "done":
                refused = bool(event.data.get("refused", False))
                first_token_ms = event.data.get("first_token_ms")
                total_ms = int(event.data.get("total_ms", 0))
                model_name = event.data.get("model", model_name) or model_name
                used_hits = event.data.get("hits", used_hits)
                answer = event.data.get("answer", "") or "".join(answer_parts)
                log_id = self.write_log(
                    session_id=session_id,
                    question=request.question,
                    answer=answer,
                    hit_ids=[h["id"] for h in used_hits],
                    top_score=max((h.get("score", 0.0) for h in used_hits), default=0.0),
                    refused=refused,
                    retrieve_ms=retrieve_ms,
                    first_token_ms=first_token_ms,
                    total_ms=total_ms,
                    model=model_name,
                )
                return {
                    "session_id": session_id,
                    "answer": answer,
                    "raw_answer": event.data.get("raw_answer", answer),
                    "dropped_citations": event.data.get("dropped_citations", 0),
                    "remapped_citations": event.data.get("remapped_citations", 0),
                    "refused": refused,
                    "hits": used_hits,
                    "raw_hits": raw_hits,
                    "score_threshold": threshold,
                    "timing": {
                        "retrieve_ms": retrieve_ms,
                        "first_token_ms": first_token_ms,
                        "total_ms": total_ms,
                    },
                    "model": model_name,
                    "log_id": log_id,
                }
            elif event.type == "error":
                # 上游（大模型/嵌入模型/向量库）失败：带上真实原因，交给全局处理器转成 502
                error_message = event.data.get("message", "未知错误")

        if error_message:
            # 失败也要留痕，便于事后排查是哪一类问题导致的
            self.write_log(
                session_id=session_id,
                question=request.question,
                answer=f"[生成失败] {error_message}",
                hit_ids=[h["id"] for h in used_hits],
                top_score=max((h.get("score", 0.0) for h in used_hits), default=0.0),
                refused=False,
                retrieve_ms=retrieve_ms,
                first_token_ms=first_token_ms,
                total_ms=total_ms,
                model=model_name,
            )
            raise UpstreamError(error_message)

        raise UpstreamError("RAG 链路未产生 done 事件")


def event_to_sse(payload: Dict[str, Any]) -> str:
    """把事件字典包成统一响应格式后编码为 SSE 帧。"""
    import json

    envelope = {
        "code": 0 if payload.get("type") != "error" else 500,
        "message": payload.get("message") or "ok",
        "data": payload,
    }
    return f"event: {payload.get('type', 'message')}\ndata: {json.dumps(envelope, ensure_ascii=False)}\n\n"