"""pytest 全局夹具。

在导入 ``app.*`` **之前**设置好环境变量，保证测试使用：
Mock 嵌入 + Mock 对话模型 + LocalVectorStore + 临时 SQLite，
完全离线、互不干扰、可重复。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

TMP_ROOT = Path(tempfile.mkdtemp(prefix="campus-qa-pytest-"))

os.environ.update(
    {
        "APP_ENV": "test",
        "APP_NAME": "校园 AI 答疑助手（测试）",
        "CHAT_PROVIDER": "mock",
        "EMBEDDING_PROVIDER": "mock",
        "EMBEDDING_MODEL": "mock-embedding",
        "EMBEDDING_DIM": "256",
        "VECTOR_BACKEND": "local",
        "VECTOR_STORE_PATH": str(TMP_ROOT / "vector_store"),
        "MILVUS_COLLECTION": "campus_kb_test",
        "DATABASE_URL": f"sqlite:///{(TMP_ROOT / 'test.db').as_posix()}",
        "DB_FALLBACK_SQLITE": "false",
        "SQLITE_PATH": str(TMP_ROOT / "test.db"),
        "UPLOAD_DIR": str(TMP_ROOT / "uploads"),
        "ALLOW_MOCK_PROVIDER": "true",
        "CHUNK_STRATEGY": "recursive",
        "CHUNK_MAX_LENGTH": "200",
        "CHUNK_OVERLAP": "30",
        "RAG_TOP_K": "3",
        "RAG_SCORE_THRESHOLD": "0.02",
        "CORS_ORIGINS": "http://localhost:5173,http://127.0.0.1:5173",
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    """带 lifespan 的测试客户端（会真实执行建表与组件初始化）。"""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def container():
    return app.state.container


@pytest.fixture
def sample_txt(tmp_path: Path) -> Path:
    """一份带明显区分度的政策样例（仅用于测试链路）。"""
    text = (
        "山西大学本科学生选课管理办法（测试样例）\n\n"
        "第一条 选课时间。每学期选课分两轮进行，第一轮选课时间为开学前两周的周一至周五，"
        "每日八时至二十二时开放系统。第二轮补退选时间为开学后第一周。\n\n"
        "第二条 退课规则。学生可在补退选阶段申请退课，退课后该课程不计入本学期学分，"
        "已缴纳的学分费用按学校财务规定退还。\n\n"
        "第三条 学分上限。本科生每学期修读学分上限为三十学分，下限为十五学分，"
        "超出上限需经学院教学副院长审批。\n\n"
        "第四条 毕业学分要求。本科生须修满培养方案规定的总学分方可申请毕业，"
        "其中通识教育课程不少于四十学分，专业必修课程不少于六十学分。\n"
    )
    path = tmp_path / "选课管理办法.txt"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def sample_txt_2(tmp_path: Path) -> Path:
    text = (
        "山西大学学生学籍管理规定（测试样例）\n\n"
        "第一章 入学与注册。新生须持录取通知书在规定时间内到校办理入学手续，"
        "因故不能按期入学者，应当提前向学校请假，假期一般不得超过两周。\n\n"
        "第二章 休学与复学。学生申请休学一次以一年为期，累计不得超过两年，"
        "休学期间不享受在校学习学生待遇。\n\n"
        "第三章 转专业。转专业须在入学满一年后提出，平均学分绩点排名须位于本专业前百分之三十。\n"
    )
    path = tmp_path / "学籍管理规定.txt"
    path.write_text(text, encoding="utf-8")
    return path