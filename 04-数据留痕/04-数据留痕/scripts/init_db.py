"""建表脚本（FR-D3）：新同学 clone 仓库后一条命令完成建表。

用法::

    python scripts/init_db.py                 # 按 .env 的 DATABASE_URL 建表
    python scripts/init_db.py --create-db     # MySQL 场景：库不存在时先 CREATE DATABASE
    python scripts/init_db.py --sqlite        # 强制使用本地 SQLite（无需装 MySQL）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401,E402

from sqlalchemy import create_engine, text  # noqa: E402

from app.config import mask_dsn, settings  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.db.session import active_database_url, init_db  # noqa: E402


def create_database_if_needed(url: str) -> None:
    """连接 MySQL 服务端并创建目标数据库（如果不存在）。"""
    if not url.startswith("mysql"):
        print("· 非 MySQL 连接串，跳过建库")
        return
    # mysql+pymysql://user:pwd@host:port/dbname?charset=utf8mb4
    without_db, _, rest = url.partition("@")
    host_part, _, db_part = rest.partition("/")
    db_name = db_part.split("?", 1)[0]
    if not db_name:
        raise SystemExit("DATABASE_URL 中缺少数据库名")
    server_url = f"{without_db}@{host_part}/?{db_part.split('?', 1)[1] if '?' in db_part else ''}"
    server_url = server_url.rstrip("?&")
    engine = create_engine(server_url, future=True, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(
            text(f"CREATE DATABASE IF NOT EXISTS `{db_name}` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        )
    engine.dispose()
    print(f"· 数据库 `{db_name}` 已就绪")


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化数据库表结构")
    parser.add_argument("--create-db", action="store_true", help="MySQL 场景：数据库不存在时自动创建")
    parser.add_argument("--sqlite", action="store_true", help="强制使用本地 SQLite 文件")
    parser.add_argument("--drop", action="store_true", help="先删除已有表再重建（危险，仅用于本地重置）")
    args = parser.parse_args()

    if args.sqlite:
        path = settings.resolve(settings.sqlite_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        settings.database_url = f"sqlite:///{path.as_posix()}"
        print(f"· 强制使用 SQLite: {path}")

    # 顺序很重要：必须先建库，再探活。
    # 否则库不存在时探活就会失败并降级到 SQLite，--create-db 反而白跑一趟。
    if args.create_db:
        create_database_if_needed(settings.database_url)

    print(f"· 目标数据库: {mask_dsn(active_database_url())}")

    engine = None
    if args.drop:
        from app.db.session import get_engine

        engine = get_engine()
        Base.metadata.drop_all(engine)
        print("· 已删除旧表")

    init_db()
    tables = ", ".join(sorted(Base.metadata.tables.keys()))
    print(f"· 建表完成: {tables}")
    print("√ 现在可以启动后端: cd backend && uvicorn app.main:app --reload")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())