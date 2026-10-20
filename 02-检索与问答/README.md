# 02-检索与问答

职责：**Naive RAG 核心**——向量检索 → 提示词拼接 → 调用大模型流式生成 → 低相关度拒答（对应需求 FR-B1~B5）。

## 文件清单（相对项目根）

    路径                                        一句话职责
    backend/app/rag/text_rag.py                 Naive RAG 编排：检索→提示词→流式生成→拒答（FR-B1~B5）
    backend/app/rag/text_chat.py                对话模型调用：OpenAI 兼容流式接口（FR-B2）
    backend/app/services/qa_service.py          问答服务：会话 ID + 调 RAG + 写问答日志（模块 B+D）
    backend/tests/test_text_rag.py              RAG 检索 / 生成 / 拒答单测
    backend/tests/test_refusal_and_dims.py      拒答判定与向量维度一致性单测
    scripts/rag_cli.py                          命令行问答 / 检索入口
    scripts/eval_chunking.py                    分块策略对比评测：Hit@K / MRR / 关键词覆盖 / 拒答率

## 关键入口
- 命令行问答：`python scripts\rag_cli.py "你的问题"`
- 分块策略评测：`python scripts\eval_chunking.py`（配合 data/eval 题集）

## 跨模块依赖
- 依赖 **01** 的 `text_index` 向量库做相似度检索（用 01 入库的数据）。
- 依赖 **04** 的 db repository 写问答日志 QALog。
- 被 **03** 的 container 装配成问答服务单例，供 /api/chat 调用。
- 依赖 **03** 的 config 读取对话模型 / 检索参数。
