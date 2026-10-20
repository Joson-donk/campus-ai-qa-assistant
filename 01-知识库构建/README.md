# 01-知识库构建

职责：**把原始文档变成可检索的向量知识库**。解析 → 分块 → 嵌入 → 写入向量库 → 登记文档元数据（对应需求 FR-A1~A5）。

## 文件清单（相对项目根）

    路径                                          一句话职责
    backend/app/rag/__init__.py                   rag 包
    backend/app/rag/loader.py                     文档解析：PDF/DOCX/TXT/MD → 带页码 PageText（FR-A1）
    backend/app/rag/text_split.py                 文本分块：fixed / recursive 两种策略（FR-A2）
    backend/app/rag/text_embedding.py             文本嵌入：百炼 text-embedding-v4，支持 Mock（FR-A3）
    backend/app/rag/text_index.py                 向量库读写抽象：Local / Milvus 的 upsert + search（FR-A4）
    backend/app/services/kb_service.py            入库编排：解析→分块→嵌入→入库→登记 Document（FR-A4/A5）
    backend/tests/test_text_split.py              分块策略单测
    backend/tests/test_text_embedding.py          嵌入单测
    backend/tests/test_text_index.py              向量库读写单测
    scripts/ingest_cli.py                         命令行入库入口
    scripts/reset_local_data.py                   重置本地向量库 / 清理临时文件
    data/demo/*                                   演示语料（4 份 txt）+ 说明
    data/eval/questions.json  questions.demo.json 评测题集
    data/raw/README.md                            真实语料放置位置与格式说明

## 关键入口
- 入库：`python scripts\ingest_cli.py --dir data\demo`
- 重置本地向量库：`python scripts\reset_local_data.py`

## 跨模块依赖
- 依赖 **04** 的 db repository 做文档登记（写入 documents 表）。
- 被 **02** 复用其 `text_index` 向量库做检索；被 **03** 的 container 装配成入库服务单例。
- 依赖 **03** 的 config 读取嵌入 / 向量库配置。
