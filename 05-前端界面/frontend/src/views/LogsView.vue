<script setup>
/** 问答日志页：分页查询 MySQL/SQLite 中的留痕记录（FR-D1）。 */
import { computed, onMounted, reactive, ref } from 'vue'
import StateBlock from '@/components/StateBlock.vue'
import { api } from '@/api/client'

const rows = ref([])
const meta = ref({ page: 1, page_size: 20, total: 0, total_pages: 0 })
const loading = ref(false)
const error = ref('')
const expanded = ref(0)

const filters = reactive({ session_id: '', keyword: '', page: 1, page_size: 20 })

const summary = computed(() => {
  if (!rows.value.length) return null
  const refused = rows.value.filter((r) => r.refused).length
  const avg = Math.round(rows.value.reduce((sum, r) => sum + (r.total_ms || 0), 0) / rows.value.length)
  return { refused, avg }
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await api.logs({ ...filters })
    rows.value = data.items
    meta.value = data.meta
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

function goPage(page) {
  if (page < 1 || page > meta.value.total_pages || page === filters.page) return
  filters.page = page
  load()
}

function reset() {
  filters.session_id = ''
  filters.keyword = ''
  filters.page = 1
  load()
}

function formatTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

onMounted(load)
</script>

<template>
  <div class="page-scroll">
    <div class="container stack">
      <header>
        <h2>问答日志</h2>
        <p class="muted">每次问答都会写入数据库：会话 ID、问题、答案、命中块、耗时（FR-D1）</p>
      </header>

      <section class="card">
        <div class="card__header filters">
          <label class="field">
            <span class="field__label">会话 ID</span>
            <input v-model="filters.session_id" class="input" placeholder="精确匹配" @keyup.enter="filters.page = 1; load()" />
          </label>
          <label class="field">
            <span class="field__label">关键词</span>
            <input v-model="filters.keyword" class="input" placeholder="在问题/答案中搜索" @keyup.enter="filters.page = 1; load()" />
          </label>
          <label class="field">
            <span class="field__label">每页条数</span>
            <select v-model.number="filters.page_size" class="select" @change="filters.page = 1; load()">
              <option v-for="size in [10, 20, 50, 100]" :key="size" :value="size">{{ size }}</option>
            </select>
          </label>
          <div class="field">
            <span class="field__label">&nbsp;</span>
            <div class="row">
              <button class="btn btn--primary btn--sm" type="button" :disabled="loading" @click="filters.page = 1; load()">查询</button>
              <button class="btn btn--sm" type="button" :disabled="loading" @click="reset">重置</button>
            </div>
          </div>
        </div>

        <div class="card__body stack">
          <div v-if="error" class="alert alert--error">
            <span>⚠️</span><span style="flex: 1">{{ error }}</span>
            <button class="btn btn--sm" type="button" @click="load">重试</button>
          </div>

          <div v-if="summary" class="row stats-inline">
            <span class="badge">共 {{ meta.total }} 条</span>
            <span class="badge badge--warning">本页拒答 {{ summary.refused }} 条</span>
            <span class="badge badge--primary">本页平均耗时 {{ summary.avg }} ms</span>
          </div>

          <StateBlock v-if="loading && !rows.length" type="loading" title="正在读取日志…" />
          <StateBlock
            v-else-if="!rows.length"
            type="empty"
            title="还没有问答记录"
            hint="去「智能问答」页面提几个问题，这里就会出现完整的留痕记录。"
            action-label="刷新"
            @retry="load"
          />

          <div v-else class="table-wrap">
            <table class="table">
              <thead>
                <tr>
                  <th class="num">#</th>
                  <th>时间</th>
                  <th>会话</th>
                  <th>问题</th>
                  <th class="num">命中</th>
                  <th class="num">Top 分</th>
                  <th class="num">耗时</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                <template v-for="row in rows" :key="row.id">
                  <tr class="clickable" @click="expanded = expanded === row.id ? 0 : row.id">
                    <td class="num mono">{{ row.id }}</td>
                    <td class="faint">{{ formatTime(row.created_at) }}</td>
                    <td class="mono faint">{{ row.session_id.slice(0, 8) }}…</td>
                    <td class="q">{{ row.question }}</td>
                    <td class="num">{{ row.hit_count }}</td>
                    <td class="num mono">{{ row.top_score.toFixed(4) }}</td>
                    <td class="num mono">{{ row.total_ms }}ms</td>
                    <td>
                      <span v-if="row.refused" class="badge badge--warning">拒答</span>
                      <span v-else class="badge badge--success">已作答</span>
                    </td>
                  </tr>
                  <tr v-if="expanded === row.id" class="detail">
                    <td :colspan="8">
                      <div class="detail__grid">
                        <div>
                          <p class="field__label">答案</p>
                          <p class="detail__answer">{{ row.answer }}</p>
                        </div>
                        <div>
                          <p class="field__label">命中块 ID</p>
                          <p class="mono">{{ row.hit_ids.join(', ') || '（无）' }}</p>
                          <p class="field__label" style="margin-top: 8px">耗时明细</p>
                          <p class="mono">
                            检索 {{ row.retrieve_ms }}ms · 首字 {{ row.first_token_ms ?? '—' }}ms · 总计 {{ row.total_ms }}ms
                          </p>
                          <p class="mono faint">模型 {{ row.model || '—' }} · 策略 {{ row.strategy || '—' }}</p>
                        </div>
                      </div>
                    </td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>

          <div v-if="meta.total_pages > 1" class="row row--between pager">
            <span class="faint">第 {{ meta.page }} / {{ meta.total_pages }} 页，共 {{ meta.total }} 条</span>
            <div class="row">
              <button class="btn btn--sm" :disabled="meta.page <= 1 || loading" @click="goPage(meta.page - 1)">上一页</button>
              <button class="btn btn--sm" :disabled="meta.page >= meta.total_pages || loading" @click="goPage(meta.page + 1)">下一页</button>
            </div>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
header h2 { font-size: 17px; }
header p { font-size: 12.5px; margin-top: 2px; }
.filters { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: var(--space-3); align-items: end; }
.stats-inline { flex-wrap: wrap; }
.table-wrap { overflow-x: auto; }
.clickable { cursor: pointer; }
.q { max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.detail td { background: var(--c-surface-alt); }
.detail__grid { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); gap: var(--space-4); padding: var(--space-2) 0; }
.detail__answer { white-space: pre-wrap; word-break: break-word; font-size: 13px; }
.pager { padding-top: var(--space-2); }

@media (max-width: 720px) {
  .detail__grid { grid-template-columns: 1fr; }
}
</style>