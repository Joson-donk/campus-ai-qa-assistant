/**
 * 后端接口封装。
 *
 * 所有接口都返回统一响应格式 {code, message, data}（FR-C1），
 * 这里统一解包：code === 0 时返回 data，否则抛 ApiError，
 * 让页面只需要处理「成功的数据」和「失败的原因」两件事。
 */

const BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(message, code = -1, data = null, status = 0) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.data = data
    this.status = status
  }
}

function unwrap(payload, status) {
  if (!payload || typeof payload !== 'object') {
    throw new ApiError(`HTTP ${status}：返回体不是合法 JSON`, status, null, status)
  }
  if (status >= 400 || payload.code !== 0) {
    throw new ApiError(payload.message || `HTTP ${status}`, payload.code ?? status, payload.data, status)
  }
  return payload.data
}

async function request(path, { method = 'GET', body, signal, timeout = 60000 } = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeout)
  if (signal) {
    signal.addEventListener('abort', () => controller.abort(), { once: true })
  }

  let response
  try {
    response = await fetch(`${BASE}${path}`, {
      method,
      headers: body instanceof FormData ? undefined : { 'Content-Type': 'application/json' },
      body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    })
  } catch (err) {
    if (err.name === 'AbortError') throw new ApiError('请求超时或已取消', -1, null, 0)
    throw new ApiError(`无法连接后端服务（${err.message}）。请确认已启动：uvicorn app.main:app --reload`, -1, null, 0)
  } finally {
    clearTimeout(timer)
  }

  const payload = await response.json().catch(() => null)
  return unwrap(payload, response.status)
}

function query(params = {}) {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') search.append(key, value)
  })
  const text = search.toString()
  return text ? `?${text}` : ''
}

export const api = {
  /** 非流式提问（一次性拿到完整答案与命中片段） */
  chat: (payload) => request('/api/chat', { method: 'POST', body: { ...payload, stream: false }, timeout: 120000 }),

  /** 知识库 */
  upload: (formData, onProgress) => uploadWithProgress('/api/kb/upload', formData, onProgress),
  listDocs: (keyword = '') => request(`/api/kb/list${query({ keyword })}`),
  stats: () => request('/api/kb/stats'),
  deleteDoc: (docId) => request(`/api/kb/${encodeURIComponent(docId)}`, { method: 'DELETE' }),

  /** 日志 */
  logs: (params) => request(`/api/logs${query(params)}`),

  /** 系统 */
  health: () => request('/api/health'),
}

/**
 * 用 XMLHttpRequest 上传，才能拿到真实的上传进度事件（fetch 不支持上传进度）。
 * 返回的仍然是解包后的 data。
 */
function uploadWithProgress(path, formData, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${BASE}${path}`)
    xhr.timeout = 300000
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100))
      }
    }
    xhr.onload = () => {
      let payload = null
      try {
        payload = JSON.parse(xhr.responseText)
      } catch {
        /* 保持 null，交给 unwrap 报错 */
      }
      try {
        resolve(unwrap(payload, xhr.status))
      } catch (err) {
        reject(err)
      }
    }
    xhr.onerror = () => reject(new ApiError('上传失败：网络错误', -1, null, 0))
    xhr.ontimeout = () => reject(new ApiError('上传超时', -1, null, 0))
    xhr.onabort = () => reject(new ApiError('上传已取消', -1, null, 0))
    xhr.send(formData)
  })
}

/**
 * 流式提问：POST + SSE。
 *
 * EventSource 只支持 GET，而 /api/chat 需要请求体，因此这里用
 * fetch + ReadableStream 手工解析 SSE 帧。每一帧的 data 都是
 * 统一响应格式 {code, message, data}，yield 出内层 data。
 *
 * @yields {{type:'retrieval'|'delta'|'done'|'error', ...}}
 */
export async function* streamChat(payload, signal) {
  const response = await fetch(`${BASE}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ ...payload, stream: true }),
    signal,
  })

  if (!response.ok || !response.body) {
    const payloadText = await response.json().catch(() => null)
    throw unwrap(payloadText, response.status)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      let separator
      while ((separator = buffer.indexOf('\n\n')) >= 0) {
        const frame = buffer.slice(0, separator)
        buffer = buffer.slice(separator + 2)
        const event = parseFrame(frame)
        if (event) yield event
      }
    }
    const tail = parseFrame(buffer)
    if (tail) yield tail
  } finally {
    reader.releaseLock()
  }
}

function parseFrame(frame) {
  if (!frame || !frame.trim()) return null
  const dataLines = frame
    .split('\n')
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trim())
  if (!dataLines.length) return null
  const text = dataLines.join('\n')
  if (!text || text === '{}') return null
  try {
    const envelope = JSON.parse(text)
    return envelope?.data ?? null
  } catch {
    return null
  }
}