/**
 * 会话状态（Vue3 响应式：reactive / ref / computed，不引入 Pinia，保持依赖最小）。
 *
 * 负责：会话 ID 管理、消息列表、SSE 流式接收、多轮历史拼装、中断与重试。
 */
import { computed, reactive } from 'vue'
import { ApiError, streamChat } from '@/api/client'

let seq = 0
const uid = (prefix) => `${prefix}-${Date.now().toString(36)}-${(++seq).toString(36)}`

export function newSessionId() {
  const bytes = new Uint8Array(8)
  if (globalThis.crypto?.getRandomValues) {
    globalThis.crypto.getRandomValues(bytes)
    return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  }
  return `s-${Date.now().toString(16)}-${Math.random().toString(16).slice(2, 10)}`
}

export const state = reactive({
  sessionId: newSessionId(),
  messages: [],
  streaming: false,
  error: '',
  topK: 3,
  startedAt: 0,
})

let controller = null

export const hasMessages = computed(() => state.messages.length > 0)
export const lastAssistant = computed(() => {
  for (let i = state.messages.length - 1; i >= 0; i -= 1) {
    if (state.messages[i].role === 'assistant') return state.messages[i]
  }
  return null
})

export function resetSession() {
  stopStreaming()
  state.sessionId = newSessionId()
  state.messages = []
  state.error = ''
}

export function stopStreaming() {
  if (controller) {
    controller.abort()
    controller = null
  }
  const pending = state.messages.find((m) => m.pending)
  if (pending) {
    pending.pending = false
    pending.interrupted = true
    if (!pending.content) pending.content = '（已停止生成）'
  }
  state.streaming = false
}

export function clearError() {
  state.error = ''
}

/** 取最近 N 条对话作为多轮历史（FR-B5），不含本次要发送的问题。 */
function buildHistory(limit = 6) {
  return state.messages
    .filter((m) => !m.pending && m.content && m.content.trim())
    .slice(-limit)
    .map((m) => ({ role: m.role, content: m.content }))
}

/** 发送一个问题并以流式方式接收回答。 */
export async function sendQuestion(question) {
  const text = (question || '').trim()
  if (!text || state.streaming) return

  state.error = ''
  state.messages.push({ id: uid('u'), role: 'user', content: text, createdAt: Date.now() })

  const assistant = reactive({
    id: uid('a'),
    role: 'assistant',
    content: '',
    hits: [],
    rawHits: [],
    scoreThreshold: 0,
    refused: false,
    timing: null,
    model: '',
    logId: null,
    pending: true,
    interrupted: false,
    createdAt: Date.now(),
  })
  state.messages.push(assistant)

  const history = buildHistory()
  controller = new AbortController()
  state.streaming = true
  state.startedAt = performance.now()

  try {
    for await (const event of streamChat(
      { question: text, session_id: state.sessionId, history, top_k: state.topK },
      controller.signal,
    )) {
      if (!event || !event.type) continue

      if (event.type === 'retrieval') {
        assistant.rawHits = event.raw_hits || []
        assistant.hits = event.hits || []
        assistant.scoreThreshold = event.score_threshold ?? 0
      } else if (event.type === 'delta') {
        assistant.content += event.content || ''
      } else if (event.type === 'done') {
        // done 里带的是服务端最终答案（含拒答判定），以它为准
        if (typeof event.answer === 'string' && event.answer) assistant.content = event.answer
        assistant.hits = event.hits || assistant.hits
        assistant.refused = Boolean(event.refused)
        assistant.timing = event.timing || null
        assistant.model = event.model || ''
        assistant.logId = event.log_id ?? null
      } else if (event.type === 'error') {
        state.error = event.message || '生成失败'
      }
    }
  } catch (err) {
    if (err?.name === 'AbortError') {
      assistant.interrupted = true
    } else {
      state.error = err instanceof ApiError ? err.message : String(err?.message || err)
    }
  } finally {
    assistant.pending = false
    if (!assistant.content && !assistant.interrupted) {
      assistant.content = state.error || '（未收到任何内容）'
      assistant.failed = true
    }
    state.streaming = false
    controller = null
  }
}