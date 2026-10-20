【演示样例 · 合成数据 · 非真实政策 · 不得用于验收】

本目录下的所有文件都是为「跑通链路」而编写的合成文本，学校名称为虚构的「示例大学」。
它们**不是**山西大学的真实政策文件，不能计入项目要求的 8 份 / 50 页数据规模，
也不能写进 docs/数据来源清单.md。

用途：
1. 在没有下载到真实文档之前，先验证「解析 → 分块 → 嵌入 → 检索 → 生成」整条链路；
2. 离线（Mock 模式）运行单元测试与接口自测；
3. 演示分块策略对比脚本 scripts/eval_chunking.py 的用法。

真实数据请放入 data/raw/，参见 data/raw/README.md。

快速开始：

    python scripts/ingest_cli.py --dir data/demo
    python scripts/rag_cli.py -q "选课什么时候开始"
    python scripts/eval_chunking.py --dir data/demo --questions data/eval/questions.demo.json --skip-generation