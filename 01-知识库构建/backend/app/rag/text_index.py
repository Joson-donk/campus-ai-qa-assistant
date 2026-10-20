"""向量库与相似度检索（FR-A4 / FR-B1）。

课件要求「先手算余弦相似度，再换 Milvus」，因此这里提供两套实现，
并通过 :class:`BaseVectorStore` 抽象出完全一致的接口：

* :class:`LocalVectorStore`  —— 纯 Python/NumPy 暴力检索，落盘为本地文件。
  **它是 Windows 上的默认可用后端**：Milvus Lite 官方不支持 Windows，
  本地开发若无 Docker，用它即可跑通全链路。
* :class:`MilvusVectorStore` —— pymilvus ``MilvusClient``，
  既支持 Milvus Lite（``./data/milvus/campus.db``，Linux/macOS），
  也支持 Standalone（``http://localhost:19530``）。

字段严格对齐 FR-A4：``id``、``vector``、``text``、``source``、``page``、``chunk_index``。
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

try:  # NumPy 可选：装了就用向量化计算，没装则退回纯 Python
    import numpy as _np
except ImportError:  # pragma: no cover
    _np = None

DEFAULT_COLLECTION = "campus_kb"


class VectorStoreError(RuntimeError):
    """向量库操作失败。"""


class VectorDimensionMismatch(VectorStoreError):
    """向量维度与库中已有数据 / 集合定义不一致。

    最常见的触发场景：换了嵌入模型（或改了 ``EMBEDDING_DIM``）却复用旧的向量库目录。
    """


@dataclass
class VectorRecord:
    """一条待写入向量库的记录。"""

    id: str
    doc_id: str
    source: str
    text: str
    vector: List[float]
    page: Optional[str] = None
    chunk_index: int = 0
    strategy: str = "recursive"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Hit:
    """一次检索命中。"""

    id: str
    score: float
    text: str
    source: str
    page: Optional[str] = None
    doc_id: Optional[str] = None
    chunk_index: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# 手算余弦相似度
# ---------------------------------------------------------------------------
def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"向量维度不一致: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def cosine_topk(
    query: Sequence[float],
    vectors: Sequence[Sequence[float]],
    top_k: int = 3,
) -> List[Tuple[int, float]]:
    """暴力余弦相似度 Top-K，返回 ``(下标, 相似度)`` 列表（降序）。"""
    if not vectors:
        return []
    top_k = max(1, int(top_k))
    if _np is not None:
        matrix = _np.asarray(vectors, dtype="float32")
        q = _np.asarray(query, dtype="float32")
        norms = _np.linalg.norm(matrix, axis=1)
        qn = _np.linalg.norm(q)
        if qn == 0:
            return []
        safe = _np.where(norms == 0, 1.0, norms)
        scores = matrix @ q / (safe * qn)
        k = min(top_k, len(scores))
        idx = _np.argpartition(-scores, k - 1)[:k]
        idx = idx[_np.argsort(-scores[idx])]
        return [(int(i), float(scores[i])) for i in idx]

    scored = [(i, cosine_similarity(query, v)) for i, v in enumerate(vectors)]
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:top_k]


# ---------------------------------------------------------------------------
# 向量库抽象
# ---------------------------------------------------------------------------
class BaseVectorStore(ABC):
    """向量库统一接口。上层（RAG 链路 / API）只依赖它，不感知具体后端。"""

    name = "base"

    def __init__(self, collection: str = DEFAULT_COLLECTION, dim: int = 1024) -> None:
        self.collection = collection
        self.dim = int(dim)

    def _check_dims(self, records: Sequence[VectorRecord]) -> None:
        """写入前校验向量维度，避免把不同维度的数据混进同一个库。"""
        for record in records:
            if len(record.vector) != self.dim:
                raise VectorDimensionMismatch(
                    f"向量维度不一致：记录 {record.id} 为 {len(record.vector)} 维，"
                    f"而 {self.name} 向量库「{self.collection}」为 {self.dim} 维。"
                    f"请确认 EMBEDDING_DIM 与嵌入模型输出一致，并清空旧的向量库数据。"
                )

    @abstractmethod
    def upsert(self, records: Sequence[VectorRecord]) -> int:
        """写入（同 id 覆盖）。返回写入条数。"""

    @abstractmethod
    def search(self, query_vector: Sequence[float], top_k: int = 3) -> List[Hit]:
        """余弦相似度 Top-K 检索。"""

    @abstractmethod
    def delete_by_doc(self, doc_id: str) -> int:
        """删除某文档的全部向量，返回删除条数。"""

    @abstractmethod
    def delete_by_strategy(self, strategy: str) -> int:
        """删除指定分块策略产生的全部向量（用于分块策略对比实验）。"""

    @abstractmethod
    def count(self) -> int:
        """总块数。"""

    @abstractmethod
    def list_documents(self) -> List[Dict[str, Any]]:
        """按 doc_id 聚合：文档名、分块数、策略。"""

    @abstractmethod
    def drop(self) -> None:
        """清空集合。"""

    def close(self) -> None:  # pragma: no cover
        return None


class LocalVectorStore(BaseVectorStore):
    """本地文件向量库（暴力余弦检索）。

    落盘结构::

        <root>/vectors.npy    # float32 矩阵（有 NumPy 时）
        <root>/meta.jsonl     # 每行一条记录的元数据
        <root>/store.json     # 无 NumPy 时的完整备份
    """

    name = "local"

    def __init__(self, root: str | Path, collection: str = DEFAULT_COLLECTION, dim: int = 1024) -> None:
        super().__init__(collection, dim)
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._meta_path = self.root / "meta.jsonl"
        self._vec_path = self.root / "vectors.npy"
        self._json_path = self.root / "store.json"
        self._lock = threading.RLock()
        self._records: List[Dict[str, Any]] = []
        self._requested_dim = int(dim)
        self._load()

    # -- 持久化 ---------------------------------------------------------
    def _load(self) -> None:
        """从磁盘载入记录，并**始终**执行维度校验。"""
        if not self._load_from_npy():
            self._load_from_json()
        self._verify_dims()

    def _load_from_npy(self) -> bool:
        """优先读 vectors.npy + meta.jsonl（体积更小、载入更快）。"""
        if not (self._vec_path.exists() and self._meta_path.exists() and _np is not None):
            return False
        try:
            vectors = _np.load(self._vec_path)
            metas = [
                json.loads(line)
                for line in self._meta_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("载入 npy 失败，回退 store.json: %s", exc)
            return False
        if len(metas) != len(vectors):
            logger.warning("npy 与 meta.jsonl 条数不一致，回退 store.json")
            return False
        for meta, vec in zip(metas, vectors):
            meta["vector"] = vec.tolist()
            self._records.append(meta)
        logger.info("LocalVectorStore 载入 %s 条记录（npy）", len(self._records))
        return True

    def _load_from_json(self) -> None:
        if not self._json_path.exists():
            return
        try:
            payload = json.loads(self._json_path.read_text(encoding="utf-8"))
            self._records = payload.get("records", [])
            logger.info("LocalVectorStore 载入 %s 条记录（json）", len(self._records))
        except Exception as exc:  # noqa: BLE001
            logger.warning("载入 store.json 失败，按空库启动: %s", exc)
            self._records = []

    def _verify_dims(self) -> None:
        """确认库中已有数据的维度与当前配置一致，不一致时给出可操作的修复建议。"""
        existing = {len(r.get("vector") or []) for r in self._records}
        existing.discard(0)
        if not existing:
            return
        if len(existing) > 1:
            raise VectorDimensionMismatch(
                f"本地向量库 {self.root} 中存在多种维度的向量 {sorted(existing)}，数据已损坏。"
                f"请删除该目录后重新执行 python scripts/ingest_cli.py 入库。"
            )
        stored_dim = next(iter(existing))
        if stored_dim != self._requested_dim:
            raise VectorDimensionMismatch(
                f"本地向量库维度不匹配：{self.root} 中已存有 {stored_dim} 维向量，"
                f"而当前嵌入模型配置为 {self._requested_dim} 维。修复方式（任选其一）："
                f"(1) 删除目录 {self.root} 后重新入库；"
                f"(2) 修改 VECTOR_STORE_PATH 指向一个新目录；"
                f"(3) 把 EMBEDDING_DIM / 嵌入模型改回 {stored_dim} 维。"
            )
        self.dim = stored_dim

    def _persist(self) -> None:
        tmp = self._json_path.with_suffix(".tmp")
        payload = {"collection": self.collection, "dim": self.dim, "records": self._records}
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._json_path)

        if _np is not None and self._records:
            matrix = _np.asarray([r["vector"] for r in self._records], dtype="float32")
            _np.save(self._vec_path, matrix)
            with open(self._meta_path, "w", encoding="utf-8") as fp:
                for record in self._records:
                    meta = {k: v for k, v in record.items() if k != "vector"}
                    fp.write(json.dumps(meta, ensure_ascii=False) + "\n")
        else:
            self._vec_path.unlink(missing_ok=True)
            self._meta_path.unlink(missing_ok=True)

    # -- 接口实现 -------------------------------------------------------
    def upsert(self, records: Sequence[VectorRecord]) -> int:
        self._check_dims(records)
        with self._lock:
            index = {r["id"]: i for i, r in enumerate(self._records)}
            for record in records:
                data = record.to_dict()
                if record.id in index:
                    self._records[index[record.id]] = data
                else:
                    index[record.id] = len(self._records)
                    self._records.append(data)
            self._persist()
            return len(records)

    def search(self, query_vector: Sequence[float], top_k: int = 3) -> List[Hit]:
        with self._lock:
            if not self._records:
                return []
            vectors = [r["vector"] for r in self._records]
            ranked = cosine_topk(query_vector, vectors, top_k)
            return [
                Hit(
                    id=self._records[i]["id"],
                    score=score,
                    text=self._records[i]["text"],
                    source=self._records[i]["source"],
                    page=self._records[i].get("page"),
                    doc_id=self._records[i].get("doc_id"),
                    chunk_index=int(self._records[i].get("chunk_index", 0)),
                )
                for i, score in ranked
            ]

    def delete_by_doc(self, doc_id: str) -> int:
        return self._delete_where(lambda r: r.get("doc_id") == doc_id)

    def delete_by_strategy(self, strategy: str) -> int:
        return self._delete_where(lambda r: r.get("strategy") == strategy)

    def _delete_where(self, predicate) -> int:
        with self._lock:
            before = len(self._records)
            self._records = [r for r in self._records if not predicate(r)]
            removed = before - len(self._records)
            if removed:
                self._persist()
            return removed

    def count(self) -> int:
        with self._lock:
            return len(self._records)

    def list_documents(self) -> List[Dict[str, Any]]:
        with self._lock:
            grouped: Dict[str, Dict[str, Any]] = {}
            for record in self._records:
                key = record.get("doc_id") or record.get("source")
                entry = grouped.setdefault(
                    key,
                    {
                        "doc_id": key,
                        "source": record.get("source"),
                        "chunk_count": 0,
                        "strategy": record.get("strategy"),
                        "pages": set(),
                    },
                )
                entry["chunk_count"] += 1
                if record.get("page"):
                    entry["pages"].add(record["page"])
            for entry in grouped.values():
                entry["pages"] = sorted(entry["pages"])
            return list(grouped.values())

    def drop(self) -> None:
        with self._lock:
            self._records = []
            self._persist()
            self._vec_path.unlink(missing_ok=True)
            self._meta_path.unlink(missing_ok=True)


class MilvusVectorStore(BaseVectorStore):
    """Milvus 向量库（Milvus Lite 本地 .db 或 Standalone）。"""

    name = "milvus"

    _TEXT_MAX_LEN = 60000
    _STR_MAX_LEN = 512

    def __init__(
        self,
        uri: str,
        token: str = "",
        collection: str = DEFAULT_COLLECTION,
        dim: int = 1024,
    ) -> None:
        super().__init__(collection, dim)
        from pymilvus import DataType, MilvusClient

        self._DataType = DataType
        self.uri = uri
        # Milvus Lite 的本地 .db 需要父目录已存在，否则报 "dir ... not exists"。
        # 在 Linux/macOS 上这一步能让 Lite 直接可用；Windows 上仍会因缺少
        # milvus_lite 而失败，由 build_vector_store 降级到 LocalVectorStore。
        if not uri.startswith(("http://", "https://", "unix:")):
            try:
                Path(uri).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:  # pragma: no cover
                logger.warning("无法创建 Milvus 数据目录 %s: %s", uri, exc)
        self._client = MilvusClient(uri=uri, token=token or "")
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        if self._client.has_collection(self.collection):
            self._verify_collection_dim()
            return
        schema = self._client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("id", self._DataType.VARCHAR, is_primary=True, max_length=190)
        schema.add_field("vector", self._DataType.FLOAT_VECTOR, dim=self.dim)
        schema.add_field("text", self._DataType.VARCHAR, max_length=self._TEXT_MAX_LEN)
        schema.add_field("source", self._DataType.VARCHAR, max_length=self._STR_MAX_LEN)
        schema.add_field("doc_id", self._DataType.VARCHAR, max_length=128)
        schema.add_field("page", self._DataType.VARCHAR, max_length=self._STR_MAX_LEN)
        schema.add_field("chunk_index", self._DataType.INT64)
        schema.add_field("strategy", self._DataType.VARCHAR, max_length=32)

        index_params = self._client.prepare_index_params()
        index_params.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
        self._client.create_collection(
            collection_name=self.collection,
            schema=schema,
            index_params=index_params,
        )
        logger.info("Milvus 集合已创建: %s (dim=%s)", self.collection, self.dim)

    def _verify_collection_dim(self) -> None:
        """已有集合的向量维度必须与当前嵌入模型一致，否则报错信息会非常难懂。"""
        try:
            info = self._client.describe_collection(self.collection)
        except Exception as exc:  # noqa: BLE001
            logger.warning("describe_collection 失败，跳过维度校验: %s", exc)
            return
        for field in info.get("fields", []) or []:
            if field.get("name") != "vector":
                continue
            params = field.get("params", {}) or {}
            remote_dim = int(params.get("dim", 0) or 0)
            if remote_dim and remote_dim != self.dim:
                raise VectorDimensionMismatch(
                    f"Milvus 集合「{self.collection}」的向量维度为 {remote_dim}，"
                    f"而当前嵌入模型输出 {self.dim} 维。请重建集合（drop 后重启服务）"
                    f"或把 EMBEDDING_DIM 改回 {remote_dim}。"
                )

    @staticmethod
    def _clip(value: Optional[str], limit: int) -> str:
        return (value or "")[:limit]

    def _row(self, record: VectorRecord) -> Dict[str, Any]:
        return {
            "id": record.id[:190],
            "vector": list(record.vector),
            "text": record.text[: self._TEXT_MAX_LEN],
            "source": self._clip(record.source, self._STR_MAX_LEN),
            "doc_id": self._clip(record.doc_id, 128),
            "page": self._clip(record.page, self._STR_MAX_LEN),
            "chunk_index": int(record.chunk_index),
            "strategy": self._clip(record.strategy, 32),
        }

    def upsert(self, records: Sequence[VectorRecord]) -> int:
        if not records:
            return 0
        self._check_dims(records)
        rows = [self._row(r) for r in records]
        self._client.upsert(collection_name=self.collection, data=rows)
        return len(rows)

    def search(self, query_vector: Sequence[float], top_k: int = 3) -> List[Hit]:
        results = self._client.search(
            collection_name=self.collection,
            data=[list(query_vector)],
            limit=max(1, int(top_k)),
            output_fields=["text", "source", "page", "doc_id", "chunk_index"],
            search_params={"metric_type": "COSINE", "params": {}},
        )
        hits: List[Hit] = []
        for row in results[0] if results else []:
            entity = row.get("entity", {}) or {}
            hits.append(
                Hit(
                    id=str(row.get("id")),
                    score=float(row.get("distance", 0.0)),
                    text=entity.get("text", ""),
                    source=entity.get("source", ""),
                    page=entity.get("page") or None,
                    doc_id=entity.get("doc_id"),
                    chunk_index=int(entity.get("chunk_index", 0) or 0),
                )
            )
        return hits

    def delete_by_doc(self, doc_id: str) -> int:
        removed = self._count_where(f'doc_id == "{doc_id}"')
        if removed:
            self._client.delete(collection_name=self.collection, filter=f'doc_id == "{doc_id}"')
        return removed

    def delete_by_strategy(self, strategy: str) -> int:
        expr = f'strategy == "{strategy}"'
        removed = self._count_where(expr)
        if removed:
            self._client.delete(collection_name=self.collection, filter=expr)
        return removed

    def _count_where(self, expr: str) -> int:
        try:
            rows = self._client.query(
                collection_name=self.collection, filter=expr, output_fields=["id"], limit=16384
            )
            return len(rows or [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Milvus 统计失败(%s): %s", expr, exc)
            return 0

    def count(self) -> int:
        try:
            self._client.flush(self.collection)
            stats = self._client.get_collection_stats(self.collection)
            return int(stats.get("row_count", 0) or 0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_collection_stats 失败，退回 query 统计: %s", exc)
            return self._count_where('id != ""')

    def list_documents(self) -> List[Dict[str, Any]]:
        rows = self._client.query(
            collection_name=self.collection,
            filter='id != ""',
            output_fields=["doc_id", "source", "page", "strategy"],
            limit=16384,
        ) or []
        grouped: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            key = row.get("doc_id") or row.get("source")
            entry = grouped.setdefault(
                key,
                {
                    "doc_id": key,
                    "source": row.get("source"),
                    "chunk_count": 0,
                    "strategy": row.get("strategy"),
                    "pages": set(),
                },
            )
            entry["chunk_count"] += 1
            if row.get("page"):
                entry["pages"].add(row["page"])
        for entry in grouped.values():
            entry["pages"] = sorted(entry["pages"])
        return list(grouped.values())

    def drop(self) -> None:
        if self._client.has_collection(self.collection):
            self._client.drop_collection(self.collection)
        self._ensure_collection()

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:  # pragma: no cover  # noqa: BLE001
            pass


def build_vector_store(
    backend: str = "auto",
    uri: str = "",
    token: str = "",
    root: str | Path = "./data/vector_store",
    collection: str = DEFAULT_COLLECTION,
    dim: int = 1024,
) -> BaseVectorStore:
    """向量库工厂。

    ``backend`` 取值：

    * ``milvus`` —— 强制使用 Milvus，连不上就抛异常；
    * ``local``  —— 强制使用本地文件向量库；
    * ``auto``   —— 先试 Milvus，失败（Windows 无 milvus-lite / 无 Docker）自动降级为 local。
    """
    backend = (backend or "auto").strip().lower()

    if backend in ("milvus", "auto"):
        candidate = uri or os.getenv("MILVUS_URI") or "./data/milvus/campus.db"
        try:
            store = MilvusVectorStore(uri=candidate, token=token or os.getenv("MILVUS_TOKEN", ""), collection=collection, dim=dim)
            logger.info("向量库后端: Milvus (%s)", candidate)
            return store
        except Exception as exc:  # noqa: BLE001
            if backend == "milvus":
                raise RuntimeError(f"Milvus 连接失败: {exc}") from exc
            logger.warning("Milvus 不可用（%s），自动降级为 LocalVectorStore", exc)

    store = LocalVectorStore(root=root, collection=collection, dim=dim)
    logger.info("向量库后端: LocalVectorStore (%s)", store.root)
    return store