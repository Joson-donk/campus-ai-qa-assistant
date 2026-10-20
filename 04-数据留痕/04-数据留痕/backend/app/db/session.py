"""数据库会话管理（MySQL 优先，连不上时自动降级 SQLite，保证开箱即跑）。"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import mask_dsn, settings
from .models import Base

logger = logging.getLogger(__name__)

_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None
_active_url: str = ""


def _sqlite_url() -> str:
    path = settings.resolve(settings.sqlite_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.as_posix()}"


def _normalize_sqlite_url(url: str) -> str:
    """规范化 SQLite 连接串。

    ``sqlite:///./data/app.db`` 这种**相对路径**是 .env 里最常见的写法，
    但 SQLite 会相对「进程当前工作目录」解析——从 ``backend/`` 启动时就会
    因为找不到 ``data/`` 目录而抛 ``unable to open database file``。
    这里统一把相对路径解析到仓库根目录，并提前创建父目录。
    """
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return url
    raw = url[len(prefix) :]
    if not raw or raw == ":memory:":
        return url
    path = Path(raw)
    if not path.is_absolute():
        path = settings.resolve(raw)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(f"无法创建 SQLite 目录 {path.parent}: {exc}") from exc
    return f"{prefix}{path.as_posix()}"


def _ping(url: str) -> tuple[bool, str]:
    """探活。返回 ``(是否成功, 失败原因)``，原因用于给出针对性的修复建议。"""
    probe = None
    try:
        probe = create_engine(url, pool_pre_ping=True, future=True)
        with probe.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    finally:
        if probe is not None:
            try:
                probe.dispose()
            except Exception:  # noqa: BLE001
                pass


def _db_hint(reason: str, url: str) -> str:
    """把底层数据库报错翻译成可直接照做的修复建议。"""
    low = reason.lower()
    if "unknown database" in low or "1049" in low:
        return (
            "目标数据库不存在。执行 `python scripts/init_db.py --create-db` 自动建库，"
            "或手动 CREATE DATABASE，或改用 DATABASE_URL=sqlite:///./data/campus_qa.db"
        )
    if "access denied" in low or "1045" in low:
        return "账号或密码错误。请核对 DATABASE_URL 中的用户名/密码，并确认该账号有目标库的权限"
    if "can't connect" in low or "connection refused" in low or "2003" in low or "timed out" in low:
        host = url.split("@")[-1].split("/")[0] if "@" in url else "127.0.0.1:3306"
        return f"连不上数据库服务（{host}）。请确认 MySQL 已启动、端口未被防火墙拦截"
    if "no module named" in low or "moduleNotFoundError" in low:
        return "缺少数据库驱动。MySQL 请执行 `pip install PyMySQL`"
    return "请检查 DATABASE_URL 格式与数据库服务状态"


def resolve_database_url() -> str:
    """确定实际使用的数据库连接串。"""
    url = settings.database_url
    if url.startswith("sqlite"):
        return _normalize_sqlite_url(url) if url != "sqlite:///" else _sqlite_url()
    ok, reason = _ping(url)
    if ok:
        return url

    hint = _db_hint(reason, url)
    logger.warning("MySQL 连接失败: %s", reason.splitlines()[0][:200])
    logger.warning("修复建议: %s", hint)
    if settings.db_fallback_sqlite:
        fallback = _sqlite_url()
        logger.warning("已自动降级到 SQLite: %s（配置 DB_FALLBACK_SQLITE=false 可关闭降级）", fallback)
        return fallback
    raise RuntimeError(
        f"数据库不可用且未允许降级: {mask_dsn(url)}\n原因: {reason}\n修复建议: {hint}"
    )


def get_engine() -> Engine:
    global _engine, _SessionLocal, _active_url
    if _engine is None:
        _active_url = resolve_database_url()
        kwargs = {"future": True, "pool_pre_ping": True, "echo": settings.db_echo}
        if _active_url.startswith("sqlite"):
            kwargs.pop("pool_pre_ping")
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(_active_url, **kwargs)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_session_factory() -> sessionmaker:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def active_database_url() -> str:
    get_engine()
    return _active_url


def init_db() -> None:
    """建表（FR-D3：新同学 clone 后一条命令完成建表）。"""
    engine = get_engine()
    try:
        Base.metadata.create_all(engine)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"数据库初始化失败（{_active_url}）: {exc}\n"
            f"排查建议：1) 检查 DATABASE_URL 的主机/端口/账号/库名；"
            f"2) MySQL 需先建库，可执行 python scripts/init_db.py --create-db；"
            f"3) 若只想本地快速跑通，设置 DATABASE_URL=sqlite:///./data/campus_qa.db "
            f"或开启 DB_FALLBACK_SQLITE=true。"
        ) from exc
    logger.info("数据库表已就绪: %s", mask_dsn(_active_url))


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：每个请求一个 Session。"""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Session:
    """脚本 / 服务层使用的事务上下文。"""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dispose_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None