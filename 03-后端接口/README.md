# 03-后端接口

职责：**FastAPI 应用的组装层**——统一配置 / 响应 / 异常，对外暴露问答 / 知识库 / 日志 / 健康检查 HTTP 接口（对应需求 FR-C1~C3）。

## 文件清单（相对项目根）

    路径                                  一句话职责
    backend/app/__init__.py               app 包
    backend/app/main.py                   FastAPI 入口：lifespan / 路由挂载 / CORS
    backend/app/config.py                 全局配置：读 .env + 密钥脱敏
    backend/app/response.py               统一响应结构 ApiResponse（code/message/data）
    backend/app/exceptions.py             统一异常处理（FR-C3）
    backend/app/schemas.py                Pydantic 请求 / 响应模型
    backend/app/api/__init__.py           api 包
    backend/app/api/chat.py               问答接口 /api/chat（流式 SSE）
    backend/app/api/kb.py                 知识库接口 /api/kb（入库 / 文档列表）
    backend/app/api/system.py             健康检查 /api/health + 元信息
    backend/app/services/__init__.py      services 包
    backend/app/services/container.py     依赖装配：嵌入 / 向量库 / 对话 / RAG / 入库 单例
    backend/conftest.py                   pytest 共享 fixtures（测试 app 实例等）
    backend/pytest.ini                    pytest 配置
    backend/tests/__init__.py             tests 包
    backend/tests/test_api.py             接口集成测试
    backend/tests/test_config.py          配置读取 / 脱敏单测
    scripts/smoke_test.py                 真机联调自检脚本

## 关键入口
- 启动：`cd backend ;  python -m uvicorn app.main:app --reload --port 8000`
- 联调自检：`python scripts\smoke_test.py`
- 测试：`cd backend ;  python -m pytest`

## 跨模块依赖
- 组装 **01**（kb_service / 嵌入 / 向量库）与 **02**（qa_service / 对话 / RAG）。
- 挂载 **04** 的 `/api/logs` 接口，并用 04 的 session 在启动时建库。
- 依赖 **05** 前端通过 HTTP 调用本模块接口（本模块不反向依赖前端）。
