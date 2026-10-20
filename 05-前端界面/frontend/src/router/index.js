import { createRouter, createWebHashHistory } from 'vue-router'
import ChatView from '@/views/ChatView.vue'
import KnowledgeBaseView from '@/views/KnowledgeBaseView.vue'
import LogsView from '@/views/LogsView.vue'

const routes = [
  { path: '/', redirect: '/chat' },
  { path: '/chat', name: 'chat', component: ChatView, meta: { title: '智能问答' } },
  { path: '/kb', name: 'kb', component: KnowledgeBaseView, meta: { title: '知识库管理' } },
  { path: '/logs', name: 'logs', component: LogsView, meta: { title: '问答日志' } },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

router.afterEach((to) => {
  const base = import.meta.env.VITE_APP_TITLE || '校园 AI 答疑助手'
  document.title = to.meta?.title ? `${to.meta.title} · ${base}` : base
})

export default router