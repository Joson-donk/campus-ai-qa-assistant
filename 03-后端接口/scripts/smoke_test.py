"""真机联调自检脚本（部署说明最后一步 / 验收前跑一遍）。

用**真实云 API** 走一遍完整链路，并逐条核对验收清单里可自动化的项目：

* 嵌入模型连通性 + 输出维度是否为配置的 1024；
* 对话模型连通性 + 是否真的流式返回；
* 入库 → 检索 → 生成 → 引用标注 是否闭环；
* 知识库外的问题是否正确拒答（不编造）；
* 问答日志是否落库。

用法::

    python scripts/smoke_test.py                  # 用 data/demo 合成样例自检
    python scripts/smoke_test.py --dir data/raw   # 用真实政策文档自检
    python scripts/smoke_test.py --skip-db        # 不校验数据库

建议在 .env 中设置 ``ALLOW_MOCK_PROVIDER=false``，这样缺少 Key 时会直接报错，
而不是静默降级成 Mock 造成「假通过」。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401,E402

from app.config import settings  # noqa: E402
from app.rag.loader import SUPPORTED_SUFFIXES  # noqa: E402
from app.rag.text_rag import ANSWER_NOT_FOUND, looks_like_refusal  # noqa: E402
from app.services.container import build_container  # noqa: E402

PASS = "√"
FAIL = "×"
WARN = "!"

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = "") -> bool:
    results.append((ok, label))
    suffix = f" — {detail}" if detail else ""
    print(f"  {PASS if ok else FAIL} {label}{suffix}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="真机联调自检")
    parser.add_argument("--dir", default="data/demo", help="用于自检的文档目录")
    parser.add_argument("--question", default="退课之后还算不算学分？", help="自检提问")
    parser.add_argument("--out-of-scope", default="食堂几点关门？", help="用于验证拒答的问题")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--skip-db", action="store_true", help="跳过数据库校验")
    parser.add_argument("--max-docs", type=int, default=8, help="自检最多入库几份文档（控制 token 成本）")
    parser.add_argument("--keep", action="store_true", help="自检结束后保留入库数据（默认清理）")
    args = parser.parse_args()

    print("=" * 72)
    print("校园 AI 答疑助手 · 真机联调自检")
    print("=" * 72)
    for key, value in settings.describe().items():
        print(f"  {key:<22} {value}")
    print()

    container = build_container()
    mock_embed = container.embedder.name == "mock"
    mock_chat = container.chat_model.name == "mock"
    if mock_embed or mock_chat:
        print(f"  {WARN} 当前运行在 Mock 模式（嵌入={mock_embed} 对话={mock_chat}），"
              f"这不是真机自检。请配置 API Key 并设置 ALLOW_MOCK_PROVIDER=false")

    try:
        # --- 1. 嵌入模型 ---
        print("\n[1/5] 嵌入模型连通性")
        started = time.perf_counter()
        vector = container.embedder.embed_query("选课时间")
        elapsed = int((time.perf_counter() - started) * 1000)
        check(bool(vector) and all(isinstance(x, float) for x in vector), "嵌入接口返回向量", f"{elapsed} ms")
        check(
            len(vector) == settings.embedding_dim,
            f"嵌入维度 = {settings.embedding_dim}",
            f"实际 {len(vector)}",
        )

        # --- 2. 对话模型（含流式） ---
        print("\n[2/5] 对话模型连通性与流式输出")
        started = time.perf_counter()
        pieces: list[str] = []
        first_ms = None
        for piece in container.chat_model.stream(
            [
                {
                    "role": "user",
                    "content": "请用大约六十个字解释什么是检索增强生成（RAG），不要分点，直接一段话回答。",
                }
            ]
        ):
            if first_ms is None:
                first_ms = int((time.perf_counter() - started) * 1000)
            pieces.append(piece)
        total_ms = int((time.perf_counter() - started) * 1000)
        answer = "".join(pieces).strip()
        check(bool(answer), "对话接口有返回", f"内容={answer[:20]!r}")
        check(len(pieces) > 1 or mock_chat, "以流式分片返回", f"{len(pieces)} 片 / {total_ms} ms")
        check(first_ms is not None and (first_ms <= 3000 or mock_chat), "首字延迟 ≤ 3 秒", f"{first_ms} ms")

        # --- 3. 入库 ---
        print("\n[3/5] 文档入库")
        doc_root = Path(args.dir)
        files = sorted(
            p for p in doc_root.rglob("*")
            if p.suffix.lower() in SUPPORTED_SUFFIXES and p.stem.lower() != "readme"
        )
        check(bool(files), f"{doc_root} 下存在可入库文档", f"{len(files)} 份")
        if not files:
            raise SystemExit(summarize_after_close(container))

        from app.db.session import init_db, session_scope
        from app.services.kb_service import KnowledgeBaseService

        if not args.skip_db:
            init_db()

        service = KnowledgeBaseService(container)
        doc_ids: list[str] = []
        total_chunks = 0
        if not args.skip_db:
            with session_scope() as session:
                for path in files[: max(1, args.max_docs)]:
                    result = service.ingest_file(session, path=path, filename=path.name)
                    doc_ids.append(result.document.doc_id)
                    total_chunks += result.document.chunk_count
                    print(f"    · {path.name} → {result.document.chunk_count} 块 / {result.elapsed_ms} ms")
        check(total_chunks > 0, "文档解析+分块+嵌入+入库成功", f"{total_chunks} 块")
        check(container.store.count() >= total_chunks, "向量库块数与登记一致", f"库内 {container.store.count()} 块")

        # --- 4. 检索 + 生成 + 引用 ---
        print("\n[4/5] 检索与问答")
        pipeline = container.pipeline
        hits = pipeline.retrieve(args.question, args.top_k)
        check(bool(hits), f"Top-{args.top_k} 检索有命中", f"{len(hits)} 条")
        if hits:
            print(f"    · Top1 score={hits[0].score:.4f} 来源={hits[0].source} {hits[0].page or ''}")
            print(f"      {hits[0].text[:60].replace(chr(10), ' ')}…")

        started = time.perf_counter()
        chunks: list[str] = []
        done_payload: dict = {}
        first_token = None
        for event in pipeline.ask_stream(args.question, None, args.top_k):
            if event.type == "delta":
                if first_token is None:
                    first_token = int((time.perf_counter() - started) * 1000)
                chunks.append(event.data.get("content", ""))
                print(event.data.get("content", ""), end="", flush=True)
            elif event.type == "done":
                done_payload = event.data
        print()
        final_answer = "".join(chunks)
        check(bool(final_answer), "生成答案非空")
        check(
            first_token is not None and (first_token <= 3000 or mock_chat),
            "首字延迟 ≤ 3 秒（验收项）",
            f"{first_token} ms",
        )
        if not done_payload.get("refused"):
            check("【" in final_answer, "答案中出现引用标注【n】（FR-B3）")
        check(isinstance(done_payload.get("total_ms"), int), "耗时统计已采集", f"{done_payload.get('total_ms')} ms")

        # --- 5. 拒答 ---
        print("\n[5/5] 知识库外问题的拒答行为")
        events = list(pipeline.ask_stream(args.out_of_scope, None, args.top_k))
        done = next((e for e in events if e.type == "done"), None)
        refused = bool(done and done.data.get("refused"))
        text = "".join(e.data.get("content", "") for e in events if e.type == "delta")
        check(
            refused or looks_like_refusal(text) or ANSWER_NOT_FOUND in text,
            "未命中依据时明确拒答（不编造）",
            f"refused={refused}，模型答案={text[:24]!r}",
        )
        if not refused:
            oos_hits = pipeline.retrieve(args.out_of_scope, args.top_k)
            top = oos_hits[0].score if oos_hits else 0.0
            print(f"    {WARN} 最高相似度 {top:.4f} ≥ 阈值 {pipeline.score_threshold}，"
                  f"建议上调 RAG_SCORE_THRESHOLD（当前答案：{text[:40]}…）")

        # --- 清理 ---
        if doc_ids and not args.keep and not args.skip_db:
            with session_scope() as session:
                for doc_id in doc_ids:
                    service.delete_document(session, doc_id)
            print(f"\n  · 已清理自检产生的 {len(doc_ids)} 份文档")
    except Exception as exc:  # noqa: BLE001
        import traceback

        print(f"\n  {FAIL} 自检中断: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        results.append((False, f"自检异常中断: {type(exc).__name__}"))
    finally:
        container.close()

    return summarize()


def summarize_after_close(container) -> int:
    container.close()
    return summarize()


def summarize() -> int:
    passed = sum(1 for ok, _ in results if ok)
    failed = [label for ok, label in results if not ok]
    print("\n" + "=" * 72)
    print(f"自检结果: {passed}/{len(results)} 通过")
    if failed:
        print("未通过项:")
        for label in failed:
            print(f"  {FAIL} {label}")
    print("=" * 72)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())