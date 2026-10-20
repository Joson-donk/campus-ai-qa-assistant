"""命令行入库脚本（D1—D2 阶段产出）。

把某个目录下的所有 ``.pdf`` / ``.docx`` / ``.txt`` / ``.md`` 解析、分块、嵌入并写入向量库，
同时在 MySQL/SQLite 中登记文档信息。

用法::

    python scripts/ingest_cli.py --dir data/raw
    python scripts/ingest_cli.py --dir data/raw --strategy fixed --max-length 300 --overlap 40
    python scripts/ingest_cli.py --file 选课管理办法.pdf
    python scripts/ingest_cli.py --dir data/raw --dry-run     # 只看分块结果，不写库
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401,E402

from app.db.session import init_db, session_scope  # noqa: E402
from app.rag.loader import SUPPORTED_SUFFIXES, load_document  # noqa: E402
from app.rag.text_split import split_text  # noqa: E402
from app.services.container import build_container  # noqa: E402
from app.services.kb_service import KnowledgeBaseService  # noqa: E402

# 这些文件是说明文档而非政策正文，不入库
SKIP_FILENAMES = {"readme"}


def is_knowledge_file(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_SUFFIXES and path.stem.lower() not in SKIP_FILENAMES


def collect_files(args: argparse.Namespace) -> list[Path]:
    if args.file:
        return [Path(args.file)]
    root = Path(args.dir)
    if not root.exists():
        raise SystemExit(f"目录不存在: {root}")
    files = sorted(p for p in root.rglob("*") if is_knowledge_file(p))
    if not files:
        print(f"! {root} 下没有找到 {SUPPORTED_SUFFIXES} 文件")
    return files


def dry_run(files: list[Path], strategy: str, max_length: int, overlap: int) -> None:
    total_chunks = 0
    total_chars = 0
    for path in files:
        try:
            pages = load_document(path)
        except Exception as exc:  # noqa: BLE001
            print(f"× {path.name} 解析失败: {exc}")
            continue
        chunks = []
        for page in pages:
            chunks.extend(split_text(page.text, strategy, max_length, overlap, page=page.page))
        chars = sum(len(c.text) for c in chunks)
        total_chunks += len(chunks)
        total_chars += chars
        print(f"· {path.name:<44} 页/段={len(pages):<4} 块={len(chunks):<5} 字符={chars}")
        if chunks and args_verbose:
            print(f"    首块预览: {chunks[0].text[:80]}…")
    print(f"\n合计: {len(files)} 份文档 / {total_chunks} 块 / {total_chars} 字符")
    print("（dry-run 模式，未写入向量库）")


args_verbose = False


def main() -> int:
    global args_verbose
    parser = argparse.ArgumentParser(description="批量入库校园政策文档")
    parser.add_argument("--dir", default="data/raw", help="文档目录（默认 data/raw）")
    parser.add_argument("--file", default="", help="只入库单个文件")
    parser.add_argument("--strategy", default="", choices=["", "fixed", "recursive"], help="分块策略")
    parser.add_argument("--max-length", type=int, default=0, help="分块最大字符数")
    parser.add_argument("--overlap", type=int, default=-1, help="相邻块重叠字符数")
    parser.add_argument("--dry-run", action="store_true", help="只统计分块结果，不写库")
    parser.add_argument("-v", "--verbose", action="store_true", help="打印首块预览")
    args = parser.parse_args()
    args_verbose = args.verbose

    strategy = args.strategy or None
    max_length = args.max_length or None
    overlap = args.overlap if args.overlap >= 0 else None

    files = collect_files(args)
    if not files:
        return 1

    if args.dry_run:
        dry_run(files, strategy or "recursive", max_length or 512, max(0, overlap or 0))
        return 0

    init_db()
    container = build_container()
    service = KnowledgeBaseService(container)

    ok, failed, chunks = 0, 0, 0
    with session_scope() as session:
        for path in files:
            try:
                result = service.ingest_file(
                    session,
                    path=path,
                    filename=path.name,
                    strategy=strategy,
                    max_length=max_length,
                    chunk_overlap=overlap,
                )
                flag = "覆盖" if result.replaced else "新增"
                print(f"√ [{flag}] {path.name} → {result.document.chunk_count} 块（{result.elapsed_ms} ms）")
                ok += 1
                chunks += result.document.chunk_count
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                print(f"× {path.name} 入库失败: {exc}")
                failed += 1

    stats = container.store.count()
    print(f"\n完成: 成功 {ok} 份 / 失败 {failed} 份 / 本次 {chunks} 块 / 向量库总计 {stats} 块")
    print(f"向量库后端: {container.store.name} | 集合: {container.store.collection}")
    container.close()
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())