"""命令行端到端问答（D3—D4 阶段产出）。

在终端完成「向量化 → 检索 → 拼提示词 → 流式生成」的一次完整问答，
不启动 FastAPI，用于快速验证 RAG 链路。

用法::

    python scripts/rag_cli.py -q "选课什么时候开始"
    python scripts/rag_cli.py -q "退课呢" --history user:"选课什么时候开始" assistant:"..."
    python scripts/rag_cli.py            # 进入交互式多轮对话
    python scripts/rag_cli.py -q "..." --top-k 5 --show-prompt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401,E402

from app.rag.text_rag import build_messages  # noqa: E402
from app.services.container import build_container  # noqa: E402


def ask_once(container, question: str, history: list[dict], top_k: int, show_prompt: bool) -> None:
    pipeline = container.pipeline
    hits = pipeline.filter_by_threshold(pipeline.retrieve(question, top_k))

    print("\n" + "=" * 72)
    print(f"问题: {question}")
    print("-" * 72)
    if not hits:
        print(f"检索: Top-{top_k} 内没有相似度 >= {pipeline.score_threshold} 的材料 → 触发拒答")
    else:
        print(f"检索: 命中 {len(hits)} 条材料（阈值 {pipeline.score_threshold}）")
        for hit in hits:
            print(f"  【{hit.index}】score={hit.score:.4f}  {hit.source}  {hit.page or ''}")
            print(f"       {hit.text[:70].replace(chr(10), ' ')}…")

    if show_prompt:
        print("-" * 72)
        print("完整提示词：")
        for message in build_messages(question, hits, history):
            print(f"[{message['role']}]\n{message['content']}\n")

    print("-" * 72)
    print("回答（流式）: ", end="", flush=True)
    for event in pipeline.ask_stream(question, history, top_k):
        if event.type == "delta":
            print(event.data.get("content", ""), end="", flush=True)
        elif event.type == "error":
            print(f"\n! 错误: {event.data.get('message')}")
        elif event.type == "done":
            data = event.data
            print(
                f"\n- 检索 {data.get('retrieve_ms')} ms | 首字 {data.get('first_token_ms')} ms "
                f"| 总计 {data.get('total_ms')} ms | 模型 {data.get('model')}"
            )
    print("=" * 72)


def parse_history(items: list[str]) -> list[dict]:
    history: list[dict] = []
    for item in items or []:
        role, _, content = item.partition(":")
        role = role.strip().lower()
        if role not in ("user", "assistant") or not content.strip():
            print(f"! 忽略非法 history 项: {item}（格式应为 user:内容 或 assistant:内容）")
            continue
        history.append({"role": role, "content": content.strip()})
    return history


def interactive(container) -> None:
    history: list[dict] = []
    print("进入交互模式，输入问题回车提问；输入 :q 退出，:reset 清空上下文，:hist 查看历史。")
    while True:
        try:
            question = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见")
            return
        if not question:
            continue
        if question in (":q", ":quit", ":exit"):
            return
        if question == ":reset":
            history.clear()
            print("· 已清空对话历史")
            continue
        if question == ":hist":
            for message in history:
                print(f"  [{message['role']}] {message['content'][:60]}")
            continue

        hits = container.pipeline.filter_by_threshold(container.pipeline.retrieve(question))
        answer_parts: list[str] = []
        print("助手> ", end="", flush=True)
        for event in container.pipeline.ask_stream(question, history):
            if event.type == "delta":
                piece = event.data.get("content", "")
                answer_parts.append(piece)
                print(piece, end="", flush=True)
            elif event.type == "done":
                data = event.data
                for hit in data.get("hits", []):
                    print(f"\n    引用【{hit['index']}】{hit['source']} {hit.get('page') or ''} (score={hit['score']:.4f})", end="")
                print(f"\n    [检索 {data.get('retrieve_ms')}ms / 总计 {data.get('total_ms')}ms]", end="")
        print()
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": "".join(answer_parts)})
        history = history[-container.settings.rag_history_messages :]
        _ = hits


def main() -> int:
    parser = argparse.ArgumentParser(description="命令行 RAG 问答")
    parser.add_argument("-q", "--question", default="", help="要提问的问题；不传则进入交互模式")
    parser.add_argument("--top-k", type=int, default=0, help="检索条数（默认取配置）")
    parser.add_argument("--history", action="append", default=[], help="历史消息，格式 user:内容 / assistant:内容")
    parser.add_argument("--show-prompt", action="store_true", help="打印拼接后的完整提示词")
    args = parser.parse_args()

    container = build_container()
    info = container.describe()
    print(
        f"向量库={info['vector_backend']} 集合={info['collection']} 块数={info['chunk_count']} "
        f"嵌入={info['embedding_model']} 对话={info['chat_model']}"
    )
    for warning in info["warnings"]:
        print(f"! {warning}")

    if info["chunk_count"] == 0:
        print("! 知识库为空，请先执行: python scripts/ingest_cli.py --dir data/raw")

    try:
        if args.question:
            ask_once(container, args.question, parse_history(args.history), args.top_k or None, args.show_prompt)
        else:
            interactive(container)
    finally:
        container.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())