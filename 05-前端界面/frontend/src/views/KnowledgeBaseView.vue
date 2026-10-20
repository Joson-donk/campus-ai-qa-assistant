<script setup>
/** 知识库管理页（FR-E3 / FR-E4）。 */
import { computed, onMounted, reactive, ref } from 'vue'
import DocTable from '@/components/DocTable.vue'
import StatCards from '@/components/StatCards.vue'
import StateBlock from '@/components/StateBlock.vue'
import UploadBox from '@/components/UploadBox.vue'
import { api } from '@/api/client'

const docs = ref([])
const stats = ref(null)
const loading = ref(false)
const error = ref('')
const notice = ref('')
const keyword = ref('')
const busy = ref(false)

const state = reactive({ inconsistent: 0 })

const statItems = computed(() => {
  const s = stats.value
  if (!s) return []
  return [
    { label: '已入库文档', value: s.doc_count, hint: '项目要求 ≥ 8 份' },
    { label: '向量总块数', value: s.chunk_count, hint: `登记表 ${s.db_chunk_count} 块` },
    { label: '向量库后端', value: s.vector_backend, hint: `集合 ${s.collection}` },
    { label: '嵌入维度', value: s.embedding_dim, hint: s.embedding_model },
    { label: '正文字符数', value: s.total_char_count?.toLocaleString?.() ?? s.total_char_count, hint: `默认策略 ${s.chunk_strategy}` },
  ]
})

const filteredEmpty = computed(() => !loading.value && !error.value && docs.value.length === 0)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [listData, statsData] = await Promise.all([api.listDocs(keyword.value), api.stats()])
    docs.value = listData
    stats.value = statsData
    state.inconsistent = listData.filter((d) => !d.consistent).length
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function onDelete(doc) {
  busy.value = true
  notice.value = ''
  error.value = ''
  try {
    const data = await api.deleteDoc(doc.doc_id)
    notice.value = `已删除「${data.filename}」，同时从向量库清除 ${data.removed_chunks} 个向量块`
    await load()
  } catch (err) {
    error.value = err.message
  } finally {
    busy.value = false
  }
}

async function onUploaded(payload) {
  notice.value = `${payload.replaced ? '覆盖' : '新增'}「${payload.document.filename}」，共 ${payload.chunk_count} 块`
  await load()
}

function search() {
  load()
}

onMounted(load)
</script>

<template>
  <div class="page-scroll">
    <div class="container stack">
      <header class="row row--between">
        <div>
          <h2>知识库管理</h2>
          <p class="muted">上传校园政策文档 → 解析 → 分块 → 嵌入 → 入库，并核对登记表与向量库的块数是否一致</p>
        </div>
        <button class="btn" type="button" :disabled="loading" @click="load">
          <span v-if="loading" class="spinner" /> 刷新
        </button>
      </header>

      <!-- 请求失败态（FR-E4） -->
      <div v-if="error" class="alert alert--error">
        <span>⚠️</span>
        <div style="flex: 1"><strong>操作失败：</strong>{{ error }}</div>
        <button class="btn btn--sm" type="button" @click="load">重试</button>
      </div>

      <div v-if="notice" class="alert alert--info">
        <span>✔</span><span>{{ notice }}</span>
      </div>

      <div
        v-if="state.inconsistent > 0"
        class="alert alert--warning"
      >
        <span>!</span>
        <span>有 {{ state.inconsistent }} 份文档的登记块数与向量库实际块数不一致，请重新上传该文档。</span>
      </div>

      <StatCards :items="statItems" :loading="loading && !stats" />

      <UploadBox @uploaded="onUploaded" />

      <section class="card">
        <div class="card__header">
          <div>
            <h3 class="card__title">已入库文档</h3>
            <p class="card__subtitle">共 {{ docs.length }} 份</p>
          </div>
          <div class="row">
            <input
              v-model="keyword"
              class="input search"
              type="search"
              placeholder="按文件名搜索"
              @keyup.enter="search"
            />
            <button class="btn btn--sm" type="button" :disabled="loading" @click="search">搜索</button>
          </div>
        </div>

        <!-- 加载态 -->
        <StateBlock v-if="loading && !docs.length" type="loading" title="正在读取知识库…" />

        <!-- 空数据态 -->
        <StateBlock
          v-else-if="filteredEmpty"
          type="empty"
          :title="keyword ? `没有匹配「${keyword}」的文档` : '知识库还是空的'"
          :hint="keyword ? '换个关键词试试，或清空搜索框查看全部文档。' : '先把从山西大学官网下载的政策文档上传进来。项目要求至少 8 份、合计不少于 50 页、入库文本块不少于 300 块。'"
          :action-label="keyword ? '清空搜索' : ''"
          @retry="keyword = ''; load()"
        />

        <DocTable v-else :docs="docs" :busy="busy" @delete="onDelete" />
      </section>
    </div>
  </div>
</template>

<style scoped>
.search { width: 200px; }
header h2 { font-size: 17px; }
header p { font-size: 12.5px; margin-top: 2px; }
</style>