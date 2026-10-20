"""问答接口（模块 C）。"""

from __future__ import annotations

import json
import logging
from typing import Iterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..exceptions import UpstreamError
from ..response import ApiResponse
from ..schemas import ChatRequest, ChatResult
from ..services.qa_service import QAService, event_to_sse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["问答"])


def _qa_service(request: Request) -> QAService:
    container = request.app.state.container
    return QAService(container.pipeline, container.settings)


@router.post(
    "/chat",
    response_model=ApiResponse[ChatResult],
    summary="提问（默认 SSE 流式返回）",
    description=(
        "对知识库发起一次问答。\n\n"
        "* `stream=true`（默认）：返回 `text/event-stream`，依次为 `retrieval` → 多个 `delta` → `done`，"
        "每一帧的 `data` 都是统一响应格式 `{code, message, data}`；\n"
        "* `stream=false`：一次性返回完整 JSON，便于在 Swagger 页面直接自测。\n\n"
        "命不中任何达标材料时不会调用大模型，直接返回「知识库中未找到相关依据」。"
    ),
)
def chat(payload: ChatRequest, request: Request):
    service = _qa_service(request)

    if not payload.stream:
        result = service.chat_once(payload)
        return ApiResponse.ok(result)

    def stream() -> Iterator[str]:
        try:
            for event in service.chat_stream(payload):
                yield event_to_sse(event)
        except Exception as exc:  # noqa: BLE001
            logger.exception("SSE 流式输出异常")
            yield event_to_sse({"type": "error", "message": f"服务异常: {type(exc).__name__}"})
        finally:
            yield "event: end\ndata: {}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )