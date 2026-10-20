"""全局配置：全部来自环境变量 / ``.env``，代码中不出现任何明文密钥（FR-F4）。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List

from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent          # backend/app
BACKEND_DIR = APP_DIR.parent                       # backend
PROJECT_ROOT = BACKEND_DIR.parent                  # 仓库根目录

load_dotenv(PROJECT_ROOT / ".env", override=False)
load_dotenv(BACKEND_DIR / ".env", override=False)


def _env(key: str, default: str = "") -> str:
    value = os.getenv(key)
    return default if value is None or value == "" else value


def _env_int(key: str, default: int) -> int:
    try:
        return int(_env(key, str(default)))
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(_env(key, str(default)))
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = _env(key, str(default)).strip().lower()
    if raw in ("1", "true", "yes", "y", "on"):
        return True
    if raw in ("0", "false", "no", "n", "off"):
        return False
    return default


def _env_list(key: str, default: str) -> List[str]:
    raw = _env(key, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass
class Settings:
    # --- 应用 ---
    app_name: str = field(default_factory=lambda: _env("APP_NAME", "校园 AI 答疑助手"))
    env: str = field(default_factory=lambda: _env("APP_ENV", "dev"))
    host: str = field(default_factory=lambda: _env("APP_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _env_int("APP_PORT", 8000))
    cors_origins: List[str] = field(
        default_factory=lambda: _env_list(
            "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173"
        )
    )

    # --- 对话模型 ---
    chat_provider: str = field(default_factory=lambda: _env("CHAT_PROVIDER", "deepseek"))
    chat_api_key: str = field(default_factory=lambda: _env("CHAT_API_KEY") or _env("DEEPSEEK_API_KEY"))
    chat_base_url: str = field(default_factory=lambda: _env("CHAT_BASE_URL"))
    chat_model: str = field(default_factory=lambda: _env("CHAT_MODEL", "deepseek-chat"))
    chat_temperature: float = field(default_factory=lambda: _env_float("CHAT_TEMPERATURE", 0.2))
    chat_max_tokens: int = field(default_factory=lambda: _env_int("CHAT_MAX_TOKENS", 1200))

    # --- 嵌入模型 ---
    embedding_provider: str = field(default_factory=lambda: _env("EMBEDDING_PROVIDER", "dashscope"))
    embedding_api_key: str = field(
        default_factory=lambda: _env("EMBEDDING_API_KEY") or _env("DASHSCOPE_API_KEY")
    )
    embedding_base_url: str = field(default_factory=lambda: _env("EMBEDDING_BASE_URL"))
    embedding_model: str = field(default_factory=lambda: _env("EMBEDDING_MODEL", "text-embedding-v4"))
    embedding_dim: int = field(default_factory=lambda: _env_int("EMBEDDING_DIM", 1024))
    embedding_batch_size: int = field(default_factory=lambda: _env_int("EMBEDDING_BATCH_SIZE", 10))

    # --- 向量库 ---
    vector_backend: str = field(default_factory=lambda: _env("VECTOR_BACKEND", "auto"))
    milvus_uri: str = field(default_factory=lambda: _env("MILVUS_URI", "./data/milvus/campus.db"))
    milvus_token: str = field(default_factory=lambda: _env("MILVUS_TOKEN"))
    milvus_collection: str = field(default_factory=lambda: _env("MILVUS_COLLECTION", "campus_kb"))
    local_store_path: str = field(default_factory=lambda: _env("VECTOR_STORE_PATH", "./data/vector_store"))

    # --- 分块 ---
    chunk_strategy: str = field(default_factory=lambda: _env("CHUNK_STRATEGY", "recursive"))
    chunk_max_length: int = field(default_factory=lambda: _env_int("CHUNK_MAX_LENGTH", 512))
    chunk_overlap: int = field(default_factory=lambda: _env_int("CHUNK_OVERLAP", 64))

    # --- RAG ---
    rag_top_k: int = field(default_factory=lambda: _env_int("RAG_TOP_K", 3))
    rag_score_threshold: float = field(default_factory=lambda: _env_float("RAG_SCORE_THRESHOLD", 0.30))
    rag_max_context_chars: int = field(default_factory=lambda: _env_int("RAG_MAX_CONTEXT_CHARS", 6000))
    rag_history_messages: int = field(default_factory=lambda: _env_int("RAG_HISTORY_MESSAGES", 6))

    # --- 数据库 ---
    database_url: str = field(
        default_factory=lambda: _env(
            "DATABASE_URL", "mysql+pymysql://root:root@127.0.0.1:3306/campus_qa?charset=utf8mb4"
        )
    )
    db_fallback_sqlite: bool = field(default_factory=lambda: _env_bool("DB_FALLBACK_SQLITE", True))
    sqlite_path: str = field(default_factory=lambda: _env("SQLITE_PATH", "./data/campus_qa.db"))
    db_echo: bool = field(default_factory=lambda: _env_bool("DB_ECHO", False))

    # --- 上传 ---
    upload_dir: str = field(default_factory=lambda: _env("UPLOAD_DIR", "./data/uploads"))
    max_upload_mb: int = field(default_factory=lambda: _env_int("MAX_UPLOAD_MB", 30))

    # --- 允许无 Key 时降级到离线 Mock（本地联调用；生产请置 false） ---
    allow_mock_provider: bool = field(default_factory=lambda: _env_bool("ALLOW_MOCK_PROVIDER", True))

    def resolve(self, path: str) -> Path:
        """把配置里的相对路径解析到仓库根目录，避免因启动目录不同而写错位置。"""
        p = Path(path)
        return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def describe(self) -> dict:
        """脱敏后的配置快照（用于 /api/health 与启动日志）。"""
        def mask(value: str) -> str:
            if not value:
                return "(未配置)"
            return f"{value[:4]}***{value[-2:]}" if len(value) > 8 else "***"

        return {
            "env": self.env,
            "chat_provider": self.chat_provider,
            "chat_model": self.chat_model,
            "chat_api_key": mask(self.chat_api_key),
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "embedding_dim": self.embedding_dim,
            "embedding_api_key": mask(self.embedding_api_key),
            "vector_backend": self.vector_backend,
            "milvus_uri": self.milvus_uri,
            "chunk_strategy": self.chunk_strategy,
            "chunk_max_length": self.chunk_max_length,
            "chunk_overlap": self.chunk_overlap,
            "rag_top_k": self.rag_top_k,
            "rag_score_threshold": self.rag_score_threshold,
            "database_url": mask_dsn(self.database_url),
            "allow_mock_provider": self.allow_mock_provider,
        }


def mask_dsn(dsn: str) -> str:
    """隐藏数据库连接串中的密码。

    凡是把 DATABASE_URL 打到日志、终端或接口返回体的地方都必须先过这个函数，
    否则密码会明文出现在启动日志里。
    """
    if "@" not in dsn or "://" not in dsn:
        return dsn
    scheme, rest = dsn.split("://", 1)
    cred, host = rest.split("@", 1)
    if ":" in cred:
        user, _ = cred.split(":", 1)
        cred = f"{user}:***"
    return f"{scheme}://{cred}@{host}"


# 兼容旧名字
_mask_dsn = mask_dsn


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()