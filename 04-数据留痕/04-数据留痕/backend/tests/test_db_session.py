"""SQLite 相对路径规范化单测（真机联调中发现的问题）。"""

from __future__ import annotations

import pytest

from app.config import PROJECT_ROOT
from app.db.session import _normalize_sqlite_url


def test_relative_sqlite_path_resolves_to_project_root(tmp_path, monkeypatch):
    from app.db import session as session_module

    class FakeSettings:
        def resolve(self, value):
            path = tmp_path / value.lstrip("./")
            return path.resolve()

    monkeypatch.setattr(session_module, "settings", FakeSettings())
    url = _normalize_sqlite_url("sqlite:///./data/web.db")
    assert url == f"sqlite:///{(tmp_path / 'data' / 'web.db').resolve().as_posix()}"
    assert (tmp_path / "data").is_dir(), "父目录应被自动创建"


def test_absolute_sqlite_path_is_kept(tmp_path):
    target = tmp_path / "abs.db"
    url = _normalize_sqlite_url(f"sqlite:///{target.as_posix()}")
    assert url == f"sqlite:///{target.as_posix()}"


def test_memory_sqlite_is_kept():
    assert _normalize_sqlite_url("sqlite:///:memory:") == "sqlite:///:memory:"
    assert _normalize_sqlite_url("sqlite:///") == "sqlite:///"


def test_non_sqlite_url_is_untouched():
    dsn = "mysql+pymysql://root:pwd@127.0.0.1:3306/campus_qa?charset=utf8mb4"
    assert _normalize_sqlite_url(dsn) == dsn


def test_project_root_layout():
    """保证 config 推导出的仓库根目录确实是仓库根（里面有 backend 与 frontend）。"""
    assert (PROJECT_ROOT / "backend").is_dir()
    assert (PROJECT_ROOT / "requirements.txt").exists()