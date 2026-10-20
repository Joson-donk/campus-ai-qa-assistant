"""配置与脱敏单测（FR-F4：严禁明文密钥外泄）。"""

from __future__ import annotations

from app.config import Settings, mask_dsn


def test_mask_dsn_hides_mysql_password():
    dsn = "mysql+pymysql://root:Sup3rSecret@127.0.0.1:3306/campus_qa?charset=utf8mb4"
    masked = mask_dsn(dsn)
    assert "Sup3rSecret" not in masked
    assert masked == "mysql+pymysql://root:***@127.0.0.1:3306/campus_qa?charset=utf8mb4"


def test_mask_dsn_passes_sqlite_through():
    dsn = "sqlite:///./data/campus_qa.db"
    assert mask_dsn(dsn) == dsn


def test_describe_masks_keys(monkeypatch):
    settings = Settings()
    settings.chat_api_key = "sk-abcdefgh1234567890"
    settings.embedding_api_key = "sk-xyz"
    snapshot = settings.describe()
    assert snapshot["chat_api_key"] == "sk-a***90"
    assert snapshot["embedding_api_key"] == "***"
    assert "abcdefgh1234567890" not in str(snapshot)


def test_resolve_relative_path_against_project_root():
    from app.config import PROJECT_ROOT, settings

    resolved = settings.resolve("./data/vector_store")
    assert resolved.is_absolute()
    assert str(resolved).startswith(str(PROJECT_ROOT))


def test_resolve_absolute_path_untouched(tmp_path):
    from app.config import settings

    assert settings.resolve(str(tmp_path)) == tmp_path


def test_max_upload_bytes():
    settings = Settings()
    settings.max_upload_mb = 5
    assert settings.max_upload_bytes == 5 * 1024 * 1024


def test_mask_dsn_is_used_for_logging():
    """启动日志/接口返回体不得出现明文密码。"""
    import inspect

    from app.api import system as system_api
    from app.db import session as session_module
    from app import main as main_module

    for module in (system_api, session_module, main_module):
        src = inspect.getsource(module)
        assert "mask_dsn" in src, f"{module.__name__} 输出连接串时未脱敏"
