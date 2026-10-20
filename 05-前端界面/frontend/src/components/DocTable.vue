<script setup>
/** 文档列表（FR-E3），带删除确认与一致性校验徽标。 */
import { ref } from 'vue'

const props = defineProps({
  docs: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['delete'])

const confirming = ref('')

function formatSize(bytes) {
  if (!bytes) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

function formatTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function askDelete(doc) {
  confirming.value = doc.doc_id
}

function confirmDelete(doc) {
  confirming.value = ''
  emit('delete', doc)
}
</script>

<template>
  <div class="table-wrap">
    <table class="table">
      <thead>
        <tr>
          <th>文档名</th>
          <th class="num">分块数</th>
          <th class="num">页/段</th>
          <th>分块策略</th>
          <th class="num">大小</th>
          <th>入库时间</th>
          <th class="num">操作</th>
        </tr>
      </thead>
      <tbody>
        <!-- FR-E5：v-for 必须带唯一 key -->
        <tr v-for="doc in docs" :key="doc.doc_id">
          <td>
            <div class="cell-doc">
              <span class="cell-doc__name" :title="doc.filename">{{ doc.filename }}</span>
              <span class="mono faint">{{ doc.doc_id }}</span>
            </div>
          </td>
          <td class="num">
            <div class="row cell-chunks">
              <strong>{{ doc.chunk_count }}</strong>
              <span
                class="badge"
                :class="doc.consistent ? 'badge--success' : 'badge--danger'"
                :title="`向量库实际块数：${doc.vector_chunk_count}`"
              >
                {{ doc.consistent ? '一致' : `库内 ${doc.vector_chunk_count}` }}
              </span>
            </div>
          </td>
          <td class="num">{{ doc.page_count || '—' }}</td>
          <td><span class="badge badge--primary">{{ doc.strategy }}</span></td>
          <td class="num">{{ formatSize(doc.size_bytes) }}</td>
          <td class="faint">{{ formatTime(doc.created_at) }}</td>
          <td class="num">
            <template v-if="confirming === doc.doc_id">
              <div class="row">
                <button class="btn btn--sm btn--danger" :disabled="props.busy" @click="confirmDelete(doc)">确认删除</button>
                <button class="btn btn--sm" @click="confirming = ''">取消</button>
              </div>
            </template>
            <button v-else class="btn btn--sm btn--danger" :disabled="props.busy" @click="askDelete(doc)">删除</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.table-wrap { overflow-x: auto; }
.cell-doc { display: flex; flex-direction: column; gap: 2px; }
.cell-doc__name { font-weight: 500; }
.cell-chunks { justify-content: flex-end; gap: 6px; }
</style>