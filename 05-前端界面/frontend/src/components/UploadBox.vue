<script setup>
/** 上传组件（FR-E3）：支持拖拽与点击选择，可切换分块策略与参数。 */
import { computed, reactive, ref } from 'vue'
import { api } from '@/api/client'

const emit = defineEmits(['uploaded'])

const ACCEPT = '.pdf,.docx,.txt,.md'
const dragging = ref(false)
const uploading = ref(false)
const progress = ref(0)
const error = ref('')
const result = ref(null)
const fileInput = ref(null)

const form = reactive({
  strategy: 'recursive',
  max_length: 512,
  chunk_overlap: 64,
})

const overlapInvalid = computed(
  () => form.chunk_overlap < 0 || form.chunk_overlap >= form.max_length,
)

function onDrop(event) {
  dragging.value = false
  const files = event.dataTransfer?.files
  if (files?.length) upload(files[0])
}

function pick() {
  fileInput.value?.click()
}

function onSelected(event) {
  const file = event.target.files?.[0]
  event.target.value = '' // 允许重复选择同一个文件
  if (file) upload(file)
}

async function upload(file) {
  error.value = ''
  result.value = null
  const suffix = `.${file.name.split('.').pop()?.toLowerCase() || ''}`
  if (!['.pdf', '.docx', '.txt', '.md'].includes(suffix)) {
    error.value = `不支持的文件类型 ${suffix}，仅支持 .pdf / .docx / .txt / .md`
    return
  }
  if (overlapInvalid.value) {
    error.value = '重叠字符数必须满足 0 ≤ chunk_overlap < max_length'
    return
  }

  const data = new FormData()
  data.append('file', file)
  data.append('strategy', form.strategy)
  data.append('max_length', String(form.max_length))
  data.append('chunk_overlap', String(form.chunk_overlap))

  uploading.value = true
  progress.value = 0
  try {
    const payload = await api.upload(data, (percent) => {
      progress.value = percent
    })
    result.value = payload
    emit('uploaded', payload)
  } catch (err) {
    error.value = err.message || '上传失败'
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <section class="card">
    <div class="card__header">
      <div>
        <h3 class="card__title">上传文档入库</h3>
        <p class="card__subtitle">支持 .pdf / .docx / .txt / .md；相同内容重复上传会自动覆盖旧块，不会产生重复数据</p>
      </div>
    </div>

    <div class="card__body stack">
      <div class="uploader__params">
        <label class="field">
          <span class="field__label">分块策略</span>
          <select v-model="form.strategy" class="select" :disabled="uploading">
            <option value="recursive">recursive · 递归字符分块（推荐）</option>
            <option value="fixed">fixed · 固定字符长度分块</option>
          </select>
        </label>
        <label class="field">
          <span class="field__label">max_length（字符）</span>
          <input v-model.number="form.max_length" class="input" type="number" min="16" max="8000" :disabled="uploading" />
        </label>
        <label class="field">
          <span class="field__label">chunk_overlap（字符）</span>
          <input v-model.number="form.chunk_overlap" class="input" type="number" min="0" max="4000" :disabled="uploading" />
        </label>
      </div>

      <div
        class="dropzone"
        :class="{ 'dropzone--active': dragging, 'dropzone--busy': uploading }"
        role="button"
        tabindex="0"
        @click="pick"
        @keydown.enter.prevent="pick"
        @keydown.space.prevent="pick"
        @dragover.prevent="dragging = true"
        @dragleave.prevent="dragging = false"
        @drop.prevent="onDrop"
      >
        <input ref="fileInput" type="file" :accept="ACCEPT" class="dropzone__input" @change="onSelected" />
        <span v-if="uploading" class="spinner" />
        <span v-else class="dropzone__icon">⬆</span>
        <p class="dropzone__title">{{ uploading ? `上传并解析中… ${progress}%` : '拖拽文件到这里，或点击选择文件' }}</p>
        <p class="dropzone__hint faint">单个文件不超过 30MB；PDF 需为文字版（扫描版请先 OCR）</p>
        <div v-if="uploading" class="dropzone__bar"><span :style="{ width: `${progress}%` }" /></div>
      </div>

      <div v-if="error" class="alert alert--error"><span>⚠️</span><span>{{ error }}</span></div>

      <div v-if="result" class="alert alert--info">
        <span>✔</span>
        <div>
          <strong>{{ result.replaced ? '已覆盖旧数据' : '入库成功' }}</strong>
          ：{{ result.document.filename }} → {{ result.chunk_count }} 块
          （{{ result.strategy }}，max_length={{ result.max_length }}，overlap={{ result.chunk_overlap }}，
          耗时 {{ result.elapsed_ms }}ms）
          <p class="faint mono">doc_id = {{ result.document.doc_id }}</p>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.uploader__params { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: var(--space-3); }

.dropzone {
  position: relative; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 6px; padding: var(--space-5); border: 2px dashed var(--c-border-strong); border-radius: var(--radius);
  background: var(--c-surface-alt); cursor: pointer; text-align: center; transition: border-color .15s, background .15s;
}
.dropzone:hover, .dropzone--active { border-color: var(--c-primary); background: var(--c-primary-soft); }
.dropzone--busy { cursor: progress; }
.dropzone__input { display: none; }
.dropzone__icon { font-size: 22px; color: var(--c-primary); }
.dropzone__title { font-size: 13px; font-weight: 500; }
.dropzone__hint { font-size: 12px; }
.dropzone__bar { position: absolute; left: 0; right: 0; bottom: 0; height: 3px; background: var(--c-border); border-radius: 0 0 var(--radius) var(--radius); overflow: hidden; }
.dropzone__bar span { display: block; height: 100%; background: var(--c-primary); transition: width .2s ease; }
</style>