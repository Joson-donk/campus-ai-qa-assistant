<script setup>
/**
 * 单条消息气泡（FR-E1）。
 * 助手消息支持：流式打字机光标、【n】引用高亮、可展开的参考原文、拒答标记、耗时元信息。
 */
import { computed, ref } from 'vue'
import SourceList from './SourceList.vue'

const props = defineProps({
  message: { type: Object, required: true },
})

const showSources = ref(false)

// 把答案按【n】切成片段，引用编号单独高亮
const segments = computed(() => {
  const text = props.message.content || ''
  return text.split(/(【材料\d+】|【\d+】)/g).filter((part) => part !== '')
})

const isCitation = (part) => /^【(?:材料)?\d+】$/.test(part)

const timingText = computed(() => {
  const timing = props.message.timing
  if (!timing) return ''
  const parts = [`检索 ${timing.retrieve_ms ?? 0}ms`]
  if (timing.first_token_ms != null) parts.push(`首字 ${timing.first_token_ms}ms`)
  if (timing.total_ms != null) parts.push(`总计 ${timing.total_ms}ms`)
  return parts.join(' · ')
})
</script>

<template>
  <article class="msg" :class="`msg--${message.role}`">
    <div class="msg__avatar" :aria-hidden="true">{{ message.role === 'user' ? '我' : 'AI' }}</div>

    <div class="msg__body">
      <div class="msg__meta">
        <span class="msg__role">{{ message.role === 'user' ? '我' : '答疑助手' }}</span>
        <span v-if="message.refused" class="badge badge--warning">未找到依据</span>
        <span v-if="message.pending" class="badge badge--primary">生成中</span>
        <span v-else-if="message.interrupted" class="badge">已停止</span>
        <span v-else-if="message.failed" class="badge badge--danger">失败</span>
      </div>

      <div class="msg__bubble" :class="{ 'typing-caret': message.pending }">
        <template v-for="(part, index) in segments" :key="`${message.id}-${index}`">
          <span v-if="isCitation(part)" class="cite">{{ part }}</span>
          <span v-else>{{ part }}</span>
        </template>
      </div>

      <!-- 助手消息：参考原文 + 耗时信息 -->
      <template v-if="message.role === 'assistant' && !message.pending">
        <div class="msg__actions">
          <button class="btn btn--sm btn--ghost" @click="showSources = !showSources">
            {{ showSources ? '收起参考原文' : `参考原文（${message.hits?.length || 0}）` }}
          </button>
          <span v-if="timingText" class="mono faint">{{ timingText }}</span>
          <span v-if="message.model" class="mono faint">{{ message.model }}</span>
          <span v-if="message.logId" class="mono faint">日志 #{{ message.logId }}</span>
        </div>

        <Transition name="fade">
          <div v-if="showSources" class="msg__sources">
            <SourceList :hits="message.hits || []" :threshold="message.scoreThreshold || 0" />
          </div>
        </Transition>
      </template>
    </div>
  </article>
</template>

<style scoped>
.msg { display: flex; gap: var(--space-3); align-items: flex-start; }
.msg--user { flex-direction: row-reverse; }

.msg__avatar {
  width: 30px; height: 30px; border-radius: 9px; flex-shrink: 0;
  display: grid; place-items: center; font-size: 12px; font-weight: 600;
  background: var(--c-primary-soft); color: var(--c-primary-strong);
}
.msg--user .msg__avatar { background: #e7e9ef; color: var(--c-text-muted); }

.msg__body { display: flex; flex-direction: column; gap: 6px; max-width: min(760px, 88%); }
.msg--user .msg__body { align-items: flex-end; }

.msg__meta { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--c-text-muted); }
.msg__role { font-weight: 500; }

.msg__bubble {
  padding: 10px 14px; border-radius: var(--radius);
  background: var(--c-surface); border: 1px solid var(--c-border);
  white-space: pre-wrap; word-break: break-word; font-size: 14px; line-height: 1.75;
  box-shadow: var(--shadow-sm);
}
.msg--user .msg__bubble { background: var(--c-primary); border-color: var(--c-primary); color: #fff; }
.msg__bubble:empty::before { content: '…'; color: var(--c-text-faint); }

.cite {
  color: var(--c-primary-strong); background: var(--c-primary-soft);
  border-radius: 4px; padding: 0 3px; font-size: 12px; font-weight: 600;
  margin: 0 1px;
}

.msg__actions { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); font-size: 11px; }
.msg__sources {
  border: 1px solid var(--c-border); border-radius: var(--radius);
  background: var(--c-surface-alt); padding: var(--space-3);
}

.fade-enter-active, .fade-leave-active { transition: opacity .18s ease, transform .18s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; transform: translateY(-4px); }
</style>