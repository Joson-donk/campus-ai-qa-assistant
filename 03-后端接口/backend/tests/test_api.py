"""模块 C / D 接口层集成测试。

覆盖：统一响应格式、六个核心接口、CORS、Swagger、异常处理、日志留痕、
重复上传覆盖（FR-A5）、删除后向量确实被清除、多轮追问、拒答。
"""

from __future__ import annotations

import json

import pytest


def unwrap(response, expected_status: int = 200) -> dict:
    """断言统一响应格式 {code, message, data} 并返回 data。"""
    assert response.status_code == expected_status, response.text
    body = response.json()
    assert set(body.keys()) == {"code", "message", "data"}, body
    return body


def ok_data(response) -> dict:
    body = unwrap(response)
    assert body["code"] == 0, body
    return body["data"]


def upload(client, path, **form):
    with open(path, "rb") as fp:
        return client.post(
            "/api/kb/upload",
            files={"file": (path.name, fp, "text/plain")},
            data={k: str(v) for k, v in form.items() if v is not None},
        )


@pytest.fixture
def library_txt(tmp_path):
    text = (
        "图书馆借阅管理办法（测试样例）\n\n"
        "第一条 借阅数量。本科生每人每次最多借阅十册图书，借期为三十天，可续借一次。\n\n"
        "第二条 逾期处理。图书逾期未归还的，按每册每日零点二元缴纳滞纳金，"
        "逾期超过三十天将暂停借阅权限。\n\n"
        "第三条 开馆时间。图书馆周一至周日八时开馆，二十二时闭馆，法定节假日另行通知。\n"
    )
    path = tmp_path / "图书馆借阅管理办法.txt"
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 系统 / 文档
# ---------------------------------------------------------------------------
def test_root_lists_endpoints(client):
    data = ok_data(client.get("/"))
    assert "POST /api/chat" in data["endpoints"]
    assert data["docs"] == "/docs"


def test_swagger_and_openapi_available(client):
    assert client.get("/docs").status_code == 200
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    for expected in ("/api/chat", "/api/kb/upload", "/api/kb/list", "/api/kb/stats", "/api/logs"):
        assert expected in paths, f"OpenAPI 缺少接口: {expected}"
    assert "/api/kb/{doc_id}" in paths
    # 统一响应模型应出现在 schema 中
    assert any(name.startswith("ApiResponse") for name in spec["components"]["schemas"])


def test_health_masks_secrets_and_reports_backend(client):
    data = ok_data(client.get("/api/health"))
    assert data["status"] == "ok"
    assert data["vector_backend"] == "local"
    assert data["database"].startswith("sqlite")
    cfg = data["config"]
    dumped = json.dumps(cfg, ensure_ascii=False)
    # 无论环境里有没有真实 Key，返回体都必须脱敏
    assert cfg["chat_api_key"] == "(未配置)" or "***" in cfg["chat_api_key"]
    assert cfg["embedding_api_key"] == "(未配置)" or "***" in cfg["embedding_api_key"]
    import os as _os

    for var in ("CHAT_API_KEY", "DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY", "EMBEDDING_API_KEY"):
        secret = _os.getenv(var)
        if secret and len(secret) > 8:
            assert secret not in dumped, f"{var} 泄漏到了 /api/health 返回体"
    # 数据库连接串中的密码必须被隐藏
    assert ":***@" in data["database"] or data["database"].startswith("sqlite")


def test_cors_preflight_allows_frontend(client):
    response = client.options(
        "/api/chat",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code in (200, 204)
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_unknown_route_returns_unified_404(client):
    body = unwrap(client.get("/api/not-exist"), 404)
    assert body["code"] == 404
    assert body["data"] is None


# ---------------------------------------------------------------------------
# 知识库（模块 A / C）
# ---------------------------------------------------------------------------
def test_upload_list_stats_and_delete(client, library_txt):
    result = ok_data(upload(client, library_txt))
    doc = result["document"]
    assert doc["filename"] == "图书馆借阅管理办法.txt"
    assert doc["chunk_count"] > 0
    assert doc["status"] == "ready"
    assert len(doc["content_hash"]) == 64
    assert result["strategy"] in ("fixed", "recursive")

    listing = ok_data(client.get("/api/kb/list"))
    target = next(d for d in listing if d["doc_id"] == doc["doc_id"])
    assert target["chunk_count"] == doc["chunk_count"]
    assert target["vector_chunk_count"] == doc["chunk_count"]
    assert target["consistent"] is True
    assert target["created_at"]

    stats = ok_data(client.get("/api/kb/stats"))
    assert stats["doc_count"] >= 1
    assert stats["chunk_count"] >= doc["chunk_count"]
    assert stats["vector_backend"] == "local"

    deleted = ok_data(client.delete(f"/api/kb/{doc['doc_id']}"))
    assert deleted["removed_chunks"] == doc["chunk_count"]
    assert all(d["doc_id"] != doc["doc_id"] for d in ok_data(client.get("/api/kb/list")))


def test_upload_respects_strategy_override(client, tmp_path):
    path = tmp_path / "奖学金评定办法.txt"
    path.write_text(
        "奖学金评定办法（测试样例）\n\n"
        "第一条 国家奖学金每生每年八千元，励志奖学金每生每年五千元。\n\n"
        "第二条 评定时间。每学年秋季学期第十周启动评定，第十一周完成公示。\n",
        encoding="utf-8",
    )
    result = ok_data(upload(client, path, strategy="fixed", max_length=64, chunk_overlap=8))
    assert result["strategy"] == "fixed"
    assert result["max_length"] == 64
    assert result["chunk_overlap"] == 8
    client.delete(f"/api/kb/{result['document']['doc_id']}")


def test_duplicate_upload_replaces_instead_of_duplicating(client, library_txt):
    first = ok_data(upload(client, library_txt))
    assert first["replaced"] is False
    doc_id = first["document"]["doc_id"]
    count_after_first = ok_data(client.get("/api/kb/stats"))["chunk_count"]

    second = ok_data(upload(client, library_txt))
    assert second["replaced"] is True
    assert second["document"]["doc_id"] == doc_id
    assert second["document"]["chunk_count"] == first["document"]["chunk_count"]

    count_after_second = ok_data(client.get("/api/kb/stats"))["chunk_count"]
    assert count_after_second == count_after_first, "FR-A5：重复上传不得产生重复块"

    listing = ok_data(client.get("/api/kb/list"))
    assert sum(1 for d in listing if d["doc_id"] == doc_id) == 1
    client.delete(f"/api/kb/{doc_id}")


def test_upload_rejects_unsupported_type(client, tmp_path):
    path = tmp_path / "恶意脚本.exe"
    path.write_bytes(b"MZ\x00\x01")
    with open(path, "rb") as fp:
        response = client.post("/api/kb/upload", files={"file": (path.name, fp, "application/octet-stream")})
    body = unwrap(response, 422)
    assert body["code"] == 422
    assert "不支持的文件类型" in body["message"]


def test_upload_rejects_empty_file(client, tmp_path):
    path = tmp_path / "空文件.txt"
    path.write_text("", encoding="utf-8")
    body = unwrap(upload(client, path), 422)
    assert "空" in body["message"]


def test_upload_sanitizes_path_traversal_filename(client, tmp_path):
    path = tmp_path / "policy.txt"
    path.write_text("测试文档：用于验证文件名安全处理。\n\n第一条 文件名中的路径分隔符必须被清洗。", encoding="utf-8")
    with open(path, "rb") as fp:
        response = client.post("/api/kb/upload", files={"file": ("../../etc/passwd.txt", fp, "text/plain")})
    data = ok_data(response)
    assert "/" not in data["document"]["filename"]
    assert ".." not in data["document"]["filename"]
    client.delete(f"/api/kb/{data['document']['doc_id']}")


def test_delete_missing_document_returns_404(client):
    body = unwrap(client.delete("/api/kb/does-not-exist"), 404)
    assert body["code"] == 404
    assert "文档不存在" in body["message"]


# ---------------------------------------------------------------------------
# 问答（模块 B / C）
# ---------------------------------------------------------------------------
def test_chat_non_stream_returns_answer_and_sources(client, library_txt):
    doc = ok_data(upload(client, library_txt))["document"]
    try:
        data = ok_data(
            client.post(
                "/api/chat",
                json={"question": "图书馆每人每次最多能借几本书", "stream": False},
            )
        )
        assert data["answer"]
        assert data["session_id"]
        assert data["refused"] is False
        assert data["hits"], "FR-B4：返回体必须携带命中的原文片段"
        hit = data["hits"][0]
        assert hit["source"] == "图书馆借阅管理办法.txt"
        assert "十册" in hit["text"]
        assert hit["index"] == 1
        assert data["timing"]["total_ms"] >= 0
        assert data["log_id"]
    finally:
        client.delete(f"/api/kb/{doc['doc_id']}")


def test_chat_stream_emits_sse_events(client, library_txt):
    doc = ok_data(upload(client, library_txt))["document"]
    try:
        response = client.post(
            "/api/chat",
            json={"question": "图书逾期了怎么处罚", "stream": True},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        events = []
        for line in response.text.splitlines():
            if line.startswith("data: ") and line.strip() != "data: {}":
                payload = json.loads(line[6:])
                assert set(payload.keys()) == {"code", "message", "data"}, payload
                events.append(payload["data"])

        types = [e["type"] for e in events]
        assert types[0] == "retrieval"
        assert "delta" in types
        assert "done" in types
        done = next(e for e in events if e["type"] == "done")
        streamed = "".join(e.get("content", "") for e in events if e["type"] == "delta")
        assert done["answer"] == streamed
        assert done["hits"]
    finally:
        client.delete(f"/api/kb/{doc['doc_id']}")


def test_chat_refuses_out_of_scope_question(client, container):
    pipeline = container.pipeline
    original = pipeline.score_threshold
    pipeline.score_threshold = 1.01  # 强制所有命中都不达标
    try:
        data = ok_data(client.post("/api/chat", json={"question": "食堂几点关门", "stream": False}))
        assert data["refused"] is True
        assert "知识库中未找到相关依据" in data["answer"]
        assert data["hits"] == []
    finally:
        pipeline.score_threshold = original


def test_chat_rejects_blank_question(client):
    body = unwrap(client.post("/api/chat", json={"question": "   ", "stream": False}), 422)
    assert body["code"] == 422
    assert body["data"]["errors"], "应返回字段级错误明细"


def test_chat_rejects_invalid_top_k(client):
    unwrap(client.post("/api/chat", json={"question": "选课", "top_k": 0, "stream": False}), 422)


def test_chat_multi_turn_followup(client, library_txt):
    doc = ok_data(upload(client, library_txt))["document"]
    try:
        history = [
            {"role": "user", "content": "图书馆最多能借几本书"},
            {"role": "assistant", "content": "本科生每人每次最多借阅十册图书。"},
        ]
        data = ok_data(
            client.post(
                "/api/chat",
                json={"question": "那借期是多久", "history": history, "stream": False},
            )
        )
        assert data["refused"] is False
        assert data["hits"]
        assert any("三十天" in h["text"] for h in data["hits"])
    finally:
        client.delete(f"/api/kb/{doc['doc_id']}")


# ---------------------------------------------------------------------------
# 日志（模块 D）
# ---------------------------------------------------------------------------
def test_logs_are_written_and_paginated(client, library_txt):
    doc = ok_data(upload(client, library_txt))["document"]
    try:
        session_id = "sess-integration-001"
        for question in ("图书馆几点开馆", "图书逾期怎么处理"):
            ok_data(
                client.post(
                    "/api/chat",
                    json={"question": question, "session_id": session_id, "stream": False},
                )
            )

        page = ok_data(client.get("/api/logs", params={"page": 1, "page_size": 5}))
        assert page["meta"]["total"] >= 2
        assert page["meta"]["page"] == 1
        assert page["meta"]["page_size"] == 5
        assert len(page["items"]) <= 5

        filtered = ok_data(client.get("/api/logs", params={"session_id": session_id}))
        assert filtered["meta"]["total"] == 2
        row = filtered["items"][0]
        for field in ("id", "session_id", "question", "answer", "hit_ids", "total_ms", "created_at"):
            assert field in row, f"FR-D1 字段缺失: {field}"
        assert isinstance(row["hit_ids"], list)

        single = ok_data(client.get(f"/api/logs/{row['id']}"))
        assert single["id"] == row["id"]

        searched = ok_data(client.get("/api/logs", params={"keyword": "逾期"}))
        assert searched["meta"]["total"] >= 1
    finally:
        client.delete(f"/api/kb/{doc['doc_id']}")


def test_logs_pagination_bounds_are_validated(client):
    unwrap(client.get("/api/logs", params={"page": 0}), 422)
    unwrap(client.get("/api/logs", params={"page_size": 500}), 422)


def test_missing_log_returns_404(client):
    unwrap(client.get("/api/logs/99999999"), 404)