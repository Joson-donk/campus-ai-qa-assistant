# 校园 AI 答疑助手 — 代码模块划分

> 本目录是把 `campus-ai-qa` 全栈项目按 **五大功能模块** 做的一次**只读逻辑划分**（复制，不改动原始文件）。
> 原始工程仍保留在 `E:\codex\2026-10-09\ge\outputs\campus-ai-qa`，运行请以原始工程为准（见文末「运行方式」）。
> 技术栈：FastAPI（后端）+ 手工 Naive RAG（无 LangChain）+ Vue3 / Vite（前端）+ Milvus / 本地向量库 + MySQL / SQLite。

## 一、模块总览

| 模块目录 | 职责（一句话） | 关键入口 / 文件 |
| --- | --- | --- |
| 00-项目公共与原始文档 | 共享依赖 / 配置 + 原始项目文档（不属任一业务模块） | requirements.txt、.env.example、README.md |
| 01-知识库构建 | 文档解析 → 分块 → 嵌入 → 写入向量库 + 文档登记 | backend/app/rag/{loader,text_split,text_embedding,text_index}.py、kb_service.py、scripts/ingest_cli.py |
| 02-检索与问答 | 向量检索 → 提示词拼接 → 流式生成 → 拒答（Naive RAG 核心） | backend/app/rag/{text_rag,text_chat}.py、qa_service.py、scripts/rag_cli.py |
| 03-后端接口 | FastAPI 应用：统一响应 / 异常 / 配置 + /api/chat、/api/kb、/api/health | backend/app/main.py、backend/app/api/*、services/container.py |
| 04-数据留痕 | ORM 模型 + 数据库会话 + 数据访问 + 问答日志查询接口 | backend/app/db/*、backend/app/api/logs.py、scripts/init_db.py |
| 05-前端界面 | Vue3+Vite 三页面（聊天 / 知识库 / 日志） | frontend/src/views/*、api/client.js、stores/chat.js |

## 二、目录结构

    E:\codex\2026-10-19\
    ├── README.md                     # 本文件：划分总览
    ├── 00-项目公共与原始文档\
    │   ├── requirements.txt          # Python 依赖
    │   ├── .env.example              # 配置样例
    │   └── README.md                 # 原始项目文档（未改动）
    ├── 01-知识库构建\
    │   ├── README.md
    │   ├── backend\app\rag\          # loader / text_split / text_embedding / text_index
    │   ├── backend\app\services\kb_service.py
    │   ├── backend\tests\            # 对应单测
    │   ├── data\demo\  data\eval\  data\raw\
    │   └── scripts\ingest_cli.py  reset_local_data.py
    ├── 02-检索与问答\
    │   ├── README.md
    │   ├── backend\app\rag\text_rag.py  text_chat.py
    │   ├── backend\app\services\qa_service.py
    │   ├── backend\tests\
    │   └── scripts\rag_cli.py  eval_chunking.py
    ├── 03-后端接口\
    │   ├── README.md
    │   ├── backend\app\{main,config,response,exceptions,schemas}.py
    │   ├── backend\app\api\{chat,kb,system}.py
    │   ├── backend\app\services\container.py
    │   ├── backend\conftest.py  pytest.ini
    │   ├── backend\tests\{test_api,test_config}.py
    │   └── scripts\smoke_test.py
    ├── 04-数据留痕\
    │   ├── README.md
    │   ├── backend\app\db\{models,session,repository}.py
    │   ├── backend\app\api\logs.py
    │   ├── backend\tests\test_db_session.py
    │   └── scripts\init_db.py
    └── 05-前端界面\
        ├── README.md
        └── frontend\                 # Vue3+Vite 完整前端

## 三、数据流 / 调用链路

    【入库链路（离线 / 构建知识库）】
      原始文档(PDF/DOCX/TXT/MD)
        └─[01] loader 解析 → text_split 分块 → text_embedding 嵌入
                → text_index upsert 写入向量库(Local / Milvus)
                → kb_service 登记 Document ──►[04] db: documents 表

    【问答链路（在线）】
      用户提问
        └─[05] Vue 前端 → HTTP /api/chat →[03] FastAPI
                →[02] qa_service → text_rag：向量检索(用 01 建好的库)
                      → 提示词拼接 → text_chat(OpenAI 兼容, 流式) → 流式回答
                →[04] qa_service 写 QALog ──► db: qa_logs 表
        ◄── 流式 token 逐段回传 →[05] 前端渲染

    【日志查询链路】
      [05] 日志页 → HTTP /api/logs →[03] →[04] repository 读 QALog → 列表返回

## 四、重要说明：这是「逻辑划分」，不是「可运行拆分」

- 后端代码被按职责切到 01 / 02 / 03 / 04 四个目录，它们各自只是**同一个 FastAPI 工程（app 包）的一部分子树**；单独打开其中某一模块目录**不能直接启动**。
- 要运行：回到原始工程 `outputs\campus-ai-qa`；或把各 backend 片段按「文件清单」里的相对路径合并回同一个 backend\ 目录（路径不冲突，直接覆盖合并即可）。
- 05 前端是完整可独立启动的（`npm run dev`）。

## 五、跨模块依赖（概览）

- **03 后端接口 = 组装层**：`services/container.py` 装配 01（嵌入 / 向量库 / 入库服务）与 02（对话 / RAG / 问答服务）的单例，挂载 04 的 logs 接口，并用 04 的 session 建库。
- **02 检索与问答** → 依赖 01 建好的向量库做检索 + 04 做日志落库。
- **01 知识库构建** → 依赖 04 做文档登记（db repository）。
- **04 数据留痕** → 依赖 03 的 config 读取 DATABASE_URL。
- **05 前端界面** → 仅通过 HTTP 调用 03 的接口，不直接 import 后端代码。

## 六、共享文件 & 排除项

- 共享（放在 00）：`requirements.txt`（Python 依赖）、`.env.example`（配置样例）、原始 `README.md`。
- 未复制的运行产物 / 敏感文件：`node_modules`、`dist`、`.vite`、`build`、`__pycache__`、`.pytest_cache`；`.env`（含密钥，勿提交）；`data/vector_store/*`（向量库二进制）、`data/*.db`（SQLite 运行时库）。这些在回到原始工程运行后会自动生成。

## 七、运行方式（回到原始工程 outputs\campus-ai-qa）

    1) 建虚拟环境并装依赖：  python -m venv .venv ;  .venv\Scripts\activate ;  pip install -r requirements.txt
    2) 配置 .env（参考 .env.example）：  DASHSCOPE_API_KEY、VECTOR_BACKEND=milvus|local、MILVUS_URI、DATABASE_URL、DB_FALLBACK_SQLITE 等
    3) 启动向量库 Milvus（Docker Desktop，见原始 README）
    4) 建表：                python scripts\init_db.py
    5) 入库：                python scripts\ingest_cli.py --dir data\demo
    6) 启动后端（端口 8000）：  cd backend ;  python -m uvicorn app.main:app --reload --port 8000
    7) 启动前端（端口 5173）：  cd frontend ;  npm install ;  npm run dev

## 八、文件 → 模块 归属总表

### 01-知识库构建
    backend/app/rag/__init__.py        backend/app/rag/loader.py
    backend/app/rag/text_split.py      backend/app/rag/text_embedding.py
    backend/app/rag/text_index.py      backend/app/services/kb_service.py
    backend/tests/test_text_split.py   backend/tests/test_text_embedding.py
    backend/tests/test_text_index.py   scripts/ingest_cli.py
    scripts/reset_local_data.py        data/demo/*   data/eval/*   data/raw/README.md

### 02-检索与问答
    backend/app/rag/text_rag.py        backend/app/rag/text_chat.py
    backend/app/services/qa_service.py backend/tests/test_text_rag.py
    backend/tests/test_refusal_and_dims.py   scripts/rag_cli.py
    scripts/eval_chunking.py

### 03-后端接口
    backend/app/__init__.py            backend/app/main.py
    backend/app/config.py              backend/app/response.py
    backend/app/exceptions.py          backend/app/schemas.py
    backend/app/api/__init__.py        backend/app/api/chat.py
    backend/app/api/kb.py              backend/app/api/system.py
    backend/app/services/__init__.py   backend/app/services/container.py
    backend/conftest.py                backend/pytest.ini
    backend/tests/__init__.py          backend/tests/test_api.py
    backend/tests/test_config.py       scripts/smoke_test.py

### 04-数据留痕
    backend/app/db/__init__.py         backend/app/db/models.py
    backend/app/db/session.py          backend/app/db/repository.py
    backend/app/api/logs.py            backend/tests/test_db_session.py
    scripts/init_db.py

### 05-前端界面（完整 frontend\，共 21 个文件）
    frontend/index.html  frontend/package.json  frontend/package-lock.json
    frontend/vite.config.js  frontend/.env.development
    frontend/src/main.js  frontend/src/App.vue
    frontend/src/router/index.js  frontend/src/stores/chat.js  frontend/src/api/client.js
    frontend/src/styles/main.css
    frontend/src/views/ChatView.vue  frontend/src/views/KnowledgeBaseView.vue  frontend/src/views/LogsView.vue
    frontend/src/components/{ChatInput,ChatMessage,DocTable,SourceList,StatCards,StateBlock,UploadBox}.vue

> 各模块的详细「文件清单 + 一句话职责 + 关键入口 + 跨模块依赖」见对应目录下的 README.md。

## 代码评审

所有改动都通过 Pull Request 提交，至少 1 名组员审核通过后才能合并到 main。详细步骤见 [CONTRIBUTING.md](CONTRIBUTING.md)。
