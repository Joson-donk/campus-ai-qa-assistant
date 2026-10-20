"""重置本地数据：清空向量库、上传临时文件与本地 SQLite。

什么时候需要用：

* 换了嵌入模型 / 改了 ``EMBEDDING_DIM``，启动时报 ``VectorDimensionMismatch``；
* 想从零重新入库一遍；
* 本地调试把数据搞乱了，想恢复干净状态。

**只删除本地生成物，不会碰** ``data/raw``、``data/demo``、``data/eval`` 里的文档，
也不会碰 MySQL（要清 MySQL 请用 ``python scripts/init_db.py --drop``）。

用法::

    python scripts/reset_local_data.py            # 先预览会删什么（默认不删）
    python scripts/reset_local_data.py --yes      # 确认后执行
    python scripts/reset_local_data.py --yes --include-db   # 连本地 SQLite 一起删
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401,E402

from app.config import PROJECT_ROOT  # noqa: E402

DATA_DIR = PROJECT_ROOT / "data"

# 允许清理的目录前缀（向量库与上传临时文件）
DIR_PATTERNS = ("vector_store", "milvus", "uploads")
# 允许清理的文件后缀（本地 SQLite 与临时文件）
FILE_SUFFIXES = (".db", ".db-journal", ".db-wal", ".db-shm")


def collect_targets(include_db: bool) -> list[Path]:
    """列出将被清理的目标，全部限定在 data/ 目录内。"""
    targets: list[Path] = []
    if not DATA_DIR.exists():
        return targets
    for child in sorted(DATA_DIR.iterdir()):
        if child.is_dir():
            if any(child.name.startswith(prefix) for prefix in DIR_PATTERNS):
                targets.append(child)
        elif include_db and child.suffix.lower() in FILE_SUFFIXES:
            targets.append(child)
    return targets


def remove(target: Path) -> bool:
    """删除单个目标；再次校验路径确实在 data/ 内，防止误删。"""
    resolved = target.resolve()
    if not str(resolved).startswith(str(DATA_DIR.resolve())):
        print(f"  跳过（路径校验未通过）: {resolved}")
        return False
    try:
        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()
        return True
    except OSError as exc:
        print(f"  删除失败: {resolved} ({exc})")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="重置本地向量库与临时数据")
    parser.add_argument("--yes", "-y", action="store_true", help="确认执行删除（不加则只预览）")
    parser.add_argument("--include-db", action="store_true", help="同时删除本地 SQLite 文件")
    args = parser.parse_args()

    targets = collect_targets(args.include_db)
    print(f"· 数据目录: {DATA_DIR}")
    if not targets:
        print("· 没有需要清理的本地生成物，已经是干净状态")
        return 0

    print(f"· 发现 {len(targets)} 个可清理目标：")
    for target in targets:
        kind = "目录" if target.is_dir() else "文件"
        size = ""
        if target.is_dir():
            files = list(target.rglob("*"))
            size = f"（{sum(1 for f in files if f.is_file())} 个文件）"
        else:
            size = f"（{target.stat().st_size:,} bytes）"
        print(f"    - [{kind}] data/{target.name} {size}")

    if not args.yes:
        print("\n! 预览模式，未删除任何内容。确认无误后加 --yes 执行。")
        return 0

    removed = sum(1 for target in targets if remove(target))
    print(f"\n√ 已清理 {removed}/{len(targets)} 个目标")
    print("  下一步：python scripts/ingest_cli.py --dir data/raw   （或 --dir data/demo）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())