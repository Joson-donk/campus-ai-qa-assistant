"""FastAPI 应用入口。

启动命令（在 ``backend/`` 目录下）::

    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import chat as chat_api
from .api import kb as kb_api
from .api import logs as logs_api
from .api import system as system_api
from .config import mask_dsn, settings
from .db.session import active_database_url, dispose_engine, init_db
from .exceptions import register_exception_handlers
from .response import ApiResponse
from .services.container import build_container

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("campus-qa")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("正在初始化数据库…")
    init_db()
    logger.info("正在初始化 RAG 组件…")
    app.state.container = build_container(settings)
    app.state.started_at = time.time()

    info = app.state.container.describe()
    logger.info("启动完成 | 向量库=%s | 嵌入=%s(dim=%s) | 对话=%s | 已入库块数=%s",
                info["vector_backend"], info["embedding_model"], info["embedding_dim"],
                info["chat_model"], info["chunk_count"])
    logger.info("数据库=%s", mask_dsn(active_database_url()))
    for warning in info["warnings"]:
        logger.warning(warning)

    try:
        yield
    finally:
        app.state.container.close()
        dispose_engine()
        logger.info("已释放资源，服务退出")


app = FastAPI(
    title=settings.app_name,
    description=(
        "从零手搭 Naive RAG 的校园政策答疑系统。\n\n"
        "**链路**：文本分割 → 文本嵌入 → 余弦相似度检索 → 提示词拼接 → 流式生成，"
        "不依赖 LangChain 等高层封装。\n\n"
        "**统一响应格式**：`{code, message, data}`，`code=0` 表示成功。"
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# FR-C2：必须开启 CORS，允许前端跨域调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Type", "X-Session-Id"],
)

# FR-C3：异常统一转标准响应
register_exception_handlers(app)

app.include_router(chat_api.router)
app.include_router(kb_api.router)
app.include_router(logs_api.router)
app.include_router(system_api.router)


@app.get("/", response_model=ApiResponse[dict], tags=["系统"], summary="服务信息")
def root():
    return ApiResponse.ok(
        {
            "app": settings.app_name,
            "version": app.version,
            "docs": "/docs",
            "health": "/api/health",
            "endpoints": [
                "POST /api/chat",
                "POST /api/kb/upload",
                "GET  /api/kb/list",
                "GET  /api/kb/stats",
                "DELETE /api/kb/{doc_id}",
                "GET  /api/logs",
                "GET  /api/logs/{log_id}",
                "GET  /api/health",
            ],
        }
    )


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.env == "dev")