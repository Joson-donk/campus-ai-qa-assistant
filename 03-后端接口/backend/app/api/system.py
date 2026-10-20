"""系统信息接口：健康检查与运行态自检。"""

from __future__ import annotations

import time

from fastapi import APIRouter, Request

from ..config import mask_dsn
from ..db.session import active_database_url
from ..response import ApiResponse
from ..schemas import HealthOut

router = APIRouter(tags=["系统"])


@router.get(
    "/api/health",
    response_model=ApiResponse[HealthOut],
    summary="健康检查",
    description="返回向量库后端、数据库连接、模型配置等运行态信息（密钥已脱敏），用于部署后自检。",
)
def health(request: Request):
    container = request.app.state.container
    info = container.describe()
    return ApiResponse.ok(
        {
            "status": "ok",
            "app": container.settings.app_name,
            "env": container.settings.env,
            "vector_backend": info["vector_backend"],
            "database": mask_dsn(active_database_url()),
            "embedding_model": info["embedding_model"],
            "chat_model": info["chat_model"],
            "warnings": info["warnings"],
            "config": container.settings.describe(),
        }
    )


@router.get(
    "/api/meta",
    response_model=ApiResponse[dict],
    summary="接口清单（便于前端与验收核对）",
)
def meta(request: Request):
    routes = []
    for route in request.app.routes:
        methods = getattr(route, "methods", None)
        if not methods:
            continue
        for method in sorted(methods):
            if method in ("HEAD", "OPTIONS"):
                continue
            routes.append({"method": method, "path": getattr(route, "path", "")})
    return ApiResponse.ok(
        {
            "uptime_seconds": round(time.time() - getattr(request.app.state, "started_at", time.time()), 1),
            "routes": sorted(routes, key=lambda r: r["path"]),
        }
    )