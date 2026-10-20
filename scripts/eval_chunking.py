"""分块策略对比实验（D9 阶段产出）。

对 ``fixed`` 与 ``recursive`` 两种分块策略，分别建立**互相隔离**的向量库，
用同一套测试题跑检索与生成，输出 ``docs/分块策略对比.md`` 需要的实验数据。

指标定义：

* **Hit@K（Top-K 命中率）**：期望来源文档出现在 Top-K 检索结果中的题目占比；
* **MRR@K**：期望文档首次命中名次的倒数平均值，衡量「排在第几位」；
* **答案关键词覆盖率**：答案中命中期望关键词的比例，作为答案准确率的客观代理指标；
* **拒答正确率**：对知识库外的问题（``out_of_scope: true``）正确回答「未找到依据」的比例；
* **块数 / 平均块长**：分块粒度画像。

用法::

    python scripts/eval_chunking.py --dir data/raw --questions data/eval/questions.json
    python scripts/eval_chunking.py --top-k 3 --write-docs
    python scripts/eval_chunking.py --skip-generation      # 只测检索，不花大模型 token
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401,E402

from app.config import settings  # noqa: E402
from app.rag.loader import SUPPORTED_SUFFIXES, load_document  # noqa: E402
from app.rag.text_chat import build_chat_model  # noqa: E402
from app.rag.text_embedding import build_embedder  # noqa: E402
from app.rag.text_index import LocalVectorStore, VectorRecord  # noqa: E402
from app.rag.text_rag import ANSWER_NOT_FOUND, RagPipeline  # noqa: E402
from app.rag.text_split import split_text  # noqa: E402

STRATEGIES = ("fixed", "recursive")

# 这些文件是说明文档而非政策正文，不参与入库与评测
SKIP_FILENAMES = {"readme", "readme.md", "readme.txt"}


def is_knowledge_file(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_SUFFIXES and path.stem.lower() not in SKIP_FILENAMES


@dataclass
class StrategyResult:
    strategy: str
    max_length: int
    chunk_overlap: int
    doc_count: int = 0
    chunk_count: int = 0
    avg_chunk_len: float = 0.0
    median_chunk_len: float = 0.0
    hit_at_k: float = 0.0
    mrr: float = 0.0
    keyword_coverage: float = 0.0
    refusal_accuracy: float = 0.0
    avg_retrieve_ms: float = 0.0
    avg_total_ms: float = 0.0
    ingest_seconds: float = 0.0
    details: list = field(default_factory=list)


def load_questions(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"测试题文件不存在: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    questions = data.get("questions", data) if isinstance(data, dict) else data
    if not isinstance(questions, list) or not questions:
        raise SystemExit("测试题格式应为 [{question, expect_sources, expect_keywords, out_of_scope}]")
    return questions


def build_store(
    strategy: str,
    files: list[Path],
    embedder,
    root: Path,
    max_length: int,
    chunk_overlap: int,
) -> tuple[LocalVectorStore, dict]:
    """为单个策略建立隔离的本地向量库。"""
    if root.exists():
        shutil.rmtree(root)
    store = LocalVectorStore(root=root, collection=f"eval_{strategy}", dim=embedder.dim)

    started = time.perf_counter()
    lengths: list[int] = []
    doc_count = 0
    for path in files:
        try:
            pages = load_document(path)
        except Exception as exc:  # noqa: BLE001
            print(f"  × 跳过 {path.name}: {exc}")
            continue
        chunks = []
        for page in pages:
            chunks.extend(split_text(page.text, strategy, max_length, chunk_overlap, page=page.page))
        if not chunks:
            continue
        for i, chunk in enumerate(chunks):
            chunk.chunk_index = i
        doc_id = f"eval-{path.stem}-{strategy}"
        vectors = embedder.embed_documents([c.text for c in chunks])
        store.upsert(
            [
                VectorRecord(
                    id=f"{doc_id}:{c.chunk_index:05d}",
                    doc_id=doc_id,
                    source=path.name,
                    page=c.page,
                    chunk_index=c.chunk_index,
                    text=c.text,
                    vector=vec,
                    strategy=strategy,
                )
                for c, vec in zip(chunks, vectors)
            ]
        )
        lengths.extend(len(c.text) for c in chunks)
        doc_count += 1

    profile = {
        "doc_count": doc_count,
        "chunk_count": len(lengths),
        "avg_chunk_len": round(statistics.fmean(lengths), 1) if lengths else 0.0,
        "median_chunk_len": float(statistics.median(lengths)) if lengths else 0.0,
        "ingest_seconds": round(time.perf_counter() - started, 2),
    }
    return store, profile


def matches(expect_sources: list[str], source: str) -> bool:
    return any(expect.lower() in (source or "").lower() for expect in expect_sources)


def evaluate(
    strategy: str,
    pipeline: RagPipeline,
    questions: list[dict],
    top_k: int,
    skip_generation: bool,
) -> tuple[float, float, float, float, float]:
    hit_count = 0
    mrr_total = 0.0
    keyword_hit = 0
    keyword_total = 0
    refusal_ok = 0
    refusal_total = 0
    retrieve_total = 0.0
    total_total = 0.0
    scoped = 0

    for item in questions:
        question = item["question"]
        expect_sources = item.get("expect_sources", []) or []
        expect_keywords = item.get("expect_keywords", []) or []
        out_of_scope = bool(item.get("out_of_scope", False))

        started = time.perf_counter()
        hits = pipeline.retrieve(question, top_k)
        retrieve_total += (time.perf_counter() - started) * 1000
        used = pipeline.filter_by_threshold(hits)

        if out_of_scope:
            refusal_total += 1
            if not used:
                refusal_ok += 1
            continue

        scoped += 1
        rank = 0
        for i, hit in enumerate(hits, start=1):
            if matches(expect_sources, hit.source):
                rank = i
                break
        if rank:
            hit_count += 1
            mrr_total += 1.0 / rank

        if expect_keywords and not skip_generation:
            answer_parts: list[str] = []
            for event in pipeline.ask_stream(question, None, top_k):
                if event.type == "delta":
                    answer_parts.append(event.data.get("content", ""))
                elif event.type == "done":
                    total_total += float(event.data.get("total_ms", 0))
            answer = "".join(answer_parts)
            keyword_total += len(expect_keywords)
            keyword_hit += sum(1 for kw in expect_keywords if kw and kw in answer)

    n = max(1, scoped)
    hit_rate = hit_count / n
    mrr = mrr_total / n
    coverage = (keyword_hit / keyword_total) if keyword_total else 0.0
    refusal_acc = (refusal_ok / refusal_total) if refusal_total else 0.0
    avg_retrieve = retrieve_total / max(1, len(questions))
    avg_total = (total_total / scoped) if scoped and not skip_generation else 0.0
    return hit_rate, mrr, coverage, refusal_acc, avg_retrieve, avg_total


def to_markdown(
    results: list[StrategyResult],
    top_k: int,
    embed_model: str,
    mock: bool,
    chat_model: str,
    score_threshold: float,
) -> str:
    lines = [
        f"## 实验结果（自动生成，Top-{top_k}）",
        "",
        f"- 嵌入模型：`{embed_model}`{'（Mock 离线嵌入，仅验证链路）' if mock else ''}",
        f"- 生成模型：`{chat_model}`",
        f"- 检索条数：Top-{top_k}｜拒答阈值：{score_threshold}",
        "",
        "| 指标 | 固定长度分块 fixed | 递归字符分块 recursive |",
        "|---|---|---|",
    ]

    def row(label: str, key: str, fmt="{:.2%}"):
        fixed = next((r for r in results if r.strategy == "fixed"), None)
        rec = next((r for r in results if r.strategy == "recursive"), None)
        def value(r):
            if r is None:
                return "—"
            v = getattr(r, key)
            return fmt.format(v) if isinstance(v, float) else str(v)
        lines.append(f"| {label} | {value(fixed)} | {value(rec)} |")

    row("文档数", "doc_count", "{}")
    row("分块总数", "chunk_count", "{}")
    row("平均块长（字符）", "avg_chunk_len", "{:.1f}")
    row("块长中位数", "median_chunk_len", "{:.0f}")
    row(f"Hit@{top_k} 命中率", "hit_at_k")
    row(f"MRR@{top_k}", "mrr", "{:.4f}")
    row("答案关键词覆盖率", "keyword_coverage")
    row("拒答正确率", "refusal_accuracy")
    row("平均检索耗时(ms)", "avg_retrieve_ms", "{:.1f}")
    row("平均端到端耗时(ms)", "avg_total_ms", "{:.1f}")
    row("入库耗时(s)", "ingest_seconds", "{:.2f}")

    lines += ["", "### 逐题明细", ""]
    for result in results:
        lines += [f"<details><summary>{result.strategy} 策略明细</summary>", "", "| # | 问题 | 期望来源 | 命中名次 | 得分 |", "|---|---|---|---|---|"]
        for d in result.details:
            lines.append(f"| {d['no']} | {d['question'][:28]} | {'、'.join(d['expect_sources'])[:24]} | {d['rank'] or '未命中'} | {d['score']} |")
        lines += ["", "</details>", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="两种分块策略的对比实验")
    parser.add_argument("--dir", default="data/raw", help="知识文档目录")
    parser.add_argument("--questions", default="data/eval/questions.json", help="测试题 JSON")
    parser.add_argument("--top-k", type=int, default=None, help="检索条数（默认取配置 RAG_TOP_K）")
    parser.add_argument("--max-length", type=int, default=None, help="分块最大字符数")
    parser.add_argument("--overlap", type=int, default=None, help="重叠字符数")
    parser.add_argument("--out", default="work/eval", help="结果输出目录")
    parser.add_argument("--skip-generation", action="store_true", help="只测检索，不调用大模型")
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=None,
        help="拒答阈值；Mock 嵌入建议 0.10~0.20，真实 text-embedding-v4 建议 0.30 左右",
    )
    parser.add_argument("--write-docs", action="store_true", help="把结果表写入 docs/分块策略对比.md")
    args = parser.parse_args()

    top_k = args.top_k or settings.rag_top_k
    max_length = args.max_length or settings.chunk_max_length
    chunk_overlap = args.overlap if args.overlap is not None else settings.chunk_overlap

    doc_root = Path(args.dir)
    files = sorted(p for p in doc_root.rglob("*") if is_knowledge_file(p)) if doc_root.exists() else []
    if not files:
        raise SystemExit(f"{doc_root} 下没有可用文档，请先放入真实政策文件")

    questions = load_questions(Path(args.questions))
    score_threshold = (
        args.score_threshold if args.score_threshold is not None else settings.rag_score_threshold
    )
    print(
        f"· 文档 {len(files)} 份 | 测试题 {len(questions)} 道 | Top-{top_k} "
        f"| max_length={max_length} overlap={chunk_overlap} | 拒答阈值={score_threshold}"
    )

    embedder = build_embedder(
        provider=settings.embedding_provider,
        api_key=settings.embedding_api_key or None,
        base_url=settings.embedding_base_url or None,
        model=settings.embedding_model,
        dimensions=settings.embedding_dim,
        batch_size=settings.embedding_batch_size,
        allow_mock=settings.allow_mock_provider,
    )
    chat_model = build_chat_model(
        provider=settings.chat_provider,
        api_key=settings.chat_api_key or None,
        base_url=settings.chat_base_url or None,
        model=settings.chat_model,
        allow_mock=settings.allow_mock_provider,
    )

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    results: list[StrategyResult] = []

    for strategy in STRATEGIES:
        print(f"\n=== 策略: {strategy} ===")
        store, profile = build_store(
            strategy, files, embedder, out_root / f"store_{strategy}", max_length, chunk_overlap
        )
        print(f"  入库: {profile['doc_count']} 份 / {profile['chunk_count']} 块 / 平均块长 {profile['avg_chunk_len']} 字符 / {profile['ingest_seconds']}s")

        pipeline = RagPipeline(
            embedder=embedder,
            store=store,
            chat_model=chat_model,
            top_k=top_k,
            score_threshold=score_threshold,
        )
        hit_rate, mrr, coverage, refusal_acc, avg_retrieve, avg_total = evaluate(
            strategy, pipeline, questions, top_k, args.skip_generation
        )

        details = []
        for i, item in enumerate(questions, start=1):
            if item.get("out_of_scope"):
                continue
            hits = pipeline.retrieve(item["question"], top_k)
            rank = next(
                (j for j, h in enumerate(hits, start=1) if matches(item.get("expect_sources", []), h.source)),
                0,
            )
            details.append(
                {
                    "no": i,
                    "question": item["question"],
                    "expect_sources": item.get("expect_sources", []),
                    "rank": rank,
                    "score": round(hits[0].score, 4) if hits else 0.0,
                    "top_source": hits[0].source if hits else "",
                }
            )

        result = StrategyResult(
            strategy=strategy,
            max_length=max_length,
            chunk_overlap=chunk_overlap,
            hit_at_k=hit_rate,
            mrr=mrr,
            keyword_coverage=coverage,
            refusal_accuracy=refusal_acc,
            avg_retrieve_ms=avg_retrieve,
            avg_total_ms=avg_total,
            details=details,
            **profile,
        )
        results.append(result)
        print(
            f"  Hit@{top_k}={hit_rate:.2%} | MRR={mrr:.4f} | 关键词覆盖={coverage:.2%} "
            f"| 拒答正确率={refusal_acc:.2%} | 平均检索={avg_retrieve:.1f}ms"
        )

    payload = {
        "top_k": top_k,
        "max_length": max_length,
        "chunk_overlap": chunk_overlap,
        "embedding_model": getattr(embedder, "model", embedder.name),
        "embedding_mock": embedder.name == "mock",
        "chat_model": getattr(chat_model, "model", chat_model.name),
        "question_count": len(questions),
        "score_threshold": score_threshold,
        "results": [r.__dict__ for r in results],
    }
    stamp = time.strftime("%Y%m%d-%H%M%S")
    json_path = out_root / f"chunking-eval-{stamp}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n· 明细数据已写入: {json_path}")

    markdown = to_markdown(
        results,
        top_k,
        payload["embedding_model"],
        payload["embedding_mock"],
        payload["chat_model"],
        score_threshold,
    )
    md_path = out_root / f"chunking-eval-{stamp}.md"
    md_path.write_text(markdown, encoding="utf-8")
    print(f"· 对比表已写入: {md_path}")

    if args.write_docs:
        docs_path = Path("docs/分块策略对比.md")
        if docs_path.exists():
            text = docs_path.read_text(encoding="utf-8")
            marker = "<!-- AUTO:EVAL -->"
            if marker in text:
                head = text.split(marker, 1)[0]
                docs_path.write_text(f"{head}{marker}\n\n{markdown}\n", encoding="utf-8")
                print(f"· 已更新 {docs_path}")
            else:
                docs_path.write_text(f"{text}\n\n{marker}\n\n{markdown}\n", encoding="utf-8")
                print(f"· 已追加到 {docs_path}")
        else:
            print(f"! 未找到 {docs_path}，跳过写入")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())