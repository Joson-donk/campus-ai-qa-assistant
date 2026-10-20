# 05-前端界面

职责：**用户交互界面**——Vue3 + Vite + vue-router 单页应用，三个页面：AI 问答（聊天）、知识库（入库 / 文档列表）、问答日志。仅通过 HTTP 调用后端 03 的接口。

## 文件清单（相对项目根）

    路径                                            一句话职责
    frontend/index.html                             Vite 入口 HTML
    frontend/package.json  package-lock.json        前端依赖 / 锁定文件
    frontend/vite.config.js                         Vite 构建配置（dev 代理后端）
    frontend/.env.development                       前端开发环境变量
    frontend/src/main.js                            应用入口（挂载 router / stores）
    frontend/src/App.vue                            根组件（导航 + 路由出口）
    frontend/src/router/index.js                    路由：/chat、/kb、/logs
    frontend/src/stores/chat.js                     聊天状态管理（消息 / 流式 / 会话）
    frontend/src/api/client.js                      后端 API 封装（含 SSE 流式读取）
    frontend/src/styles/main.css                    全局样式
    frontend/src/views/ChatView.vue                 页面：AI 问答
    frontend/src/views/KnowledgeBaseView.vue        页面：知识库
    frontend/src/views/LogsView.vue                 页面：问答日志
    frontend/src/components/ChatInput.vue           组件：输入框
    frontend/src/components/ChatMessage.vue         组件：消息气泡
    frontend/src/components/SourceList.vue          组件：引用来源列表
    frontend/src/components/UploadBox.vue           组件：文档上传
    frontend/src/components/DocTable.vue            组件：文档表格
    frontend/src/components/StatCards.vue           组件：统计卡片
    frontend/src/components/StateBlock.vue          组件：空 / 加载 / 错误状态块

## 关键入口
- 启动：`cd frontend ;  npm install ;  npm run dev`（默认 http://localhost:5173）

## 跨模块依赖
- 仅通过 **HTTP** 调用 **03** 后端接口（/api/chat、/api/kb、/api/logs、/api/health），不直接 import 任何后端代码。
