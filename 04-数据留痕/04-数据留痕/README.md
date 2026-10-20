# 04-数据留痕

职责：**持久化与留痕**——ORM 模型（文档登记表 + 问答日志表）、数据库会话（MySQL 优先 / SQLite 降级）、数据访问层，以及对外的问答日志查询接口（对应需求 FR-D1）。

## 文件清单（相对项目根）

    路径                                一句话职责
    backend/app/db/__init__.py          db 包
    backend/app/db/models.py            ORM 模型：Document 文档登记表 + QALog 问答日志表
    backend/app/db/session.py           数据库会话：MySQL 优先，配置后自动降级 SQLite
    backend/app/db/repository.py        数据访问：文档 CRUD + 问答日志写入 / 查询
    backend/app/api/logs.py             问答日志查询接口 /api/logs（FR-D1）
    backend/tests/test_db_session.py    数据库会话（含 SQLite 降级）单测
    scripts/init_db.py                  建表脚本（首次初始化数据库结构）

## 关键入口
- 建表：`python scripts\init_db.py`

## 跨模块依赖
- 被 **01** 调用做文档登记、被 **02** 调用写问答日志、被 **03** 挂载 /api/logs 并在启动时建库。
- 依赖 **03** 的 config 读取 DATABASE_URL / DB_FALLBACK_SQLITE。
