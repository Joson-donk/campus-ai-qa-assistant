<script setup>
import { onMounted, ref } from 'vue'
import { api } from '@/api/client'

const health = ref(null)
const healthError = ref('')

onMounted(async () => {
  try {
    health.value = await api.health()
  } catch (err) {
    healthError.value = err.message
  }
})
</script>

<template>
  <div class="app-shell">
    <!-- HTML5 语义标签：header / nav / main（SW-5） -->
    <header class="app-header">
      <div class="app-brand">
        <span class="app-brand__logo">答</span>
        <span>校园 AI 答疑助手</span>
      </div>

      <nav class="app-nav" aria-label="主导航">
        <RouterLink to="/chat">智能问答</RouterLink>
        <RouterLink to="/kb">知识库管理</RouterLink>
        <RouterLink to="/logs">问答日志</RouterLink>
      </nav>

      <div class="app-header__spacer" />

      <!-- 后端运行态：让使用者一眼看出是不是跑在 Mock / 降级模式 -->
      <div class="row" v-if="health">
        <span class="badge" :class="health.warnings.length ? 'badge--warning' : 'badge--success'">
          {{ health.warnings.length ? '降级模式' : '正常' }}
        </span>
        <span class="badge badge--primary">{{ health.vector_backend }}</span>
        <span class="badge">{{ health.chat_model }}</span>
      </div>
      <span v-else-if="healthError" class="badge badge--danger" :title="healthError">后端未连接</span>
      <span v-else class="badge">检测中…</span>
    </header>

    <main class="app-main">
      <RouterView />
    </main>
  </div>
</template>