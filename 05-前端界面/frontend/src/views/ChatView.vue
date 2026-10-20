<script setup>
/** 聊天页（FR-E1 / FR-E2 / FR-E4 / FR-E5）。 */
import { computed, nextTick, ref, watch } from 'vue'
import ChatInput from '@/components/ChatInput.vue'
import ChatMessage from '@/components/ChatMessage.vue'
import StateBlock from '@/components/StateBlock.vue'
import {
  clearError,
  hasMessages,
  resetSession,
  sendQuestion,
  state,
  stopStreaming,
} from '@/stores/chat'

const SUGGESTIONS = [
  '选课什么时候开始？',
  '退课之后还算学分吗？',
  '毕业需要修满多少学分？',
  '国家奖学金一年多少钱？',
  '转专业需要满足什么条件？',
  '食堂几点关门？', // 知识库外的问题，用来验证「拒答不编造」
]

const draft = ref('')
const scrollArea = ref(null)

const assistantCount = computed(() => state.messages.filter((m) => m.role === 'assistant').length)

async function scrollToBottom() {
  await nextTick()
  const el = scrollArea.value
  if (el) el.scrollTop = el.scrollHeight
}

// 流式输出时持续跟随到底部
watch(
  () => state.messages.map((m) => m.content.length).join(','),
  () => scrollToBottom(),
)
watch(() => state.messages.length, scrollToBottom)

function onSubmit(text) {
  sendQuestion(text).then(scrollToBottom)
}

function onStop() {
  stopStreaming()
  scrollToBottom()
}
</script>

<template>
  <div class="chat">
    <div class="chat__bar">
      <div class="row">
        <h2 class="chat__title">智能问答</h2>
        <span class="badge mono" :title="state.sessionId">会话 {{ state.sessionId.slice(0, 10) }}…</span>
        <span v-if="assistantCount" class="badge">已答 {{ assistantCount }} 轮</span>
      </div>
      <div class="row">
        <button class="btn btn--sm" type="button" :disabled="state.streaming" @click="resetSession">
          新建会话
        </button>
      </div>
    </div>

    <div ref="scrollArea" class="chat__scroll">
      <div class="container chat__container">
        <!-- 请求失败：明确的界面反馈（FR-E4） -->
        <div v-if="state.error" class="alert alert--error chat__error">
          <span>⚠️</span>
          <div>
            <strong>{{ state.error }}</strong>
            <p class="faint">请确认后端已启动、API Key 已配置，且知识库中已入库相关文档。</p>
          </div>
          <button class="btn btn--sm" type="button" @click="clearError">知道了</button>
        </div>

        <!-- 空数据态（FR-E4） -->
        <section v-if="!hasMessages" class="card chat__empty">
          <StateBlock
            type="empty"
            title="向校园政策答疑助手提问"
            hint="回答只依据知识库中的政策原文，并会标注引用出处【n】。若知识库中没有相关依据，系统会明确说明而不会编造。点击下方问题快速开始，或先去「知识库管理」上传政策文档。"
          />
          <div class="chat__suggest">
            <button
              v-for="item in SUGGESTIONS"
              :key="item"
              class="chip"
              type="button"
              @click="sendQuestion(item).then(scrollToBottom)"
            >
              {{ item }}
            </button>
          </div>
        </section>

        <!-- 消息列表：v-for 必须带唯一 key（FR-E5） -->
        <div v-else class="chat__list">
          <ChatMessage v-for="message in state.messages" :key="message.id" :message="message" />
        </div>
      </div>
    </div>

    <footer class="chat__footer">
      <div class="container">
        <ChatInput
          v-model="draft"
          :streaming="state.streaming"
          :top-k="state.topK"
          :suggestions="hasMessages ? [] : []"
          @submit="onSubmit"
          @stop="onStop"
          @update:top-k="state.topK = $event"
        />
      </div>
    </footer>
  </div>
</template>

<style scoped>
.chat { display: flex; flex-direction: column; height: 100%; }

.chat__bar {
  display: flex; align-items: center; justify-content: space-between; gap: var(--space-3);
  padding: var(--space-3) var(--space-5); background: var(--c-surface);
  border-bottom: 1px solid var(--c-border); flex-shrink: 0;
}
.chat__title { font-size: 15px; }

.chat__scroll { flex: 1; min-height: 0; overflow-y: auto; }
.chat__container { padding-top: var(--space-5); padding-bottom: var(--space-5); }
.chat__list { display: flex; flex-direction: column; gap: var(--space-5); }

.chat__error { margin-bottom: var(--space-4); align-items: center; }
.chat__error .btn { margin-left: auto; }

.chat__empty { padding: var(--space-4); }
.chat__suggest { display: flex; flex-wrap: wrap; gap: 6px; justify-content: center; padding: 0 var(--space-4) var(--space-4); }
.chip {
  padding: 6px 12px; border-radius: 999px; border: 1px solid var(--c-border-strong);
  background: var(--c-surface); color: var(--c-text-muted); font-size: 12px; font-family: inherit; cursor: pointer;
}
.chip:hover { background: var(--c-primary-soft); border-color: #cdd8fb; color: var(--c-primary-strong); }

.chat__footer {
  flex-shrink: 0; background: var(--c-surface); border-top: 1px solid var(--c-border);
  padding: var(--space-3) 0 var(--space-4);
}
</style>