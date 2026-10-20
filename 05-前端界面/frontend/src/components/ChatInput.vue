<script setup>
/** 提问输入框：v-model 双向绑定，Enter 发送、Shift+Enter 换行，支持中断生成。 */
import { ref } from 'vue'

const model = defineModel({ type: String, default: '' })

const props = defineProps({
  disabled: { type: Boolean, default: false },
  streaming: { type: Boolean, default: false },
  topK: { type: Number, default: 3 },
  suggestions: { type: Array, default: () => [] },
})
const emit = defineEmits(['submit', 'stop', 'update:topK', 'pick'])

const textarea = ref(null)

function submit() {
  const text = model.value.trim()
  if (!text || props.streaming) return
  emit('submit', text)
  model.value = ''
  // 发送后让输入框高度回落
  requestAnimationFrame(() => autoGrow())
}

function onKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    submit()
  }
}

function autoGrow() {
  const el = textarea.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 180)}px`
}

function pick(text) {
  model.value = text
  emit('pick', text)
  textarea.value?.focus()
  requestAnimationFrame(autoGrow)
}
</script>

<template>
  <div class="composer">
    <div v-if="suggestions.length" class="composer__suggestions">
      <button
        v-for="item in suggestions"
        :key="item"
        class="chip"
        type="button"
        :disabled="streaming"
        @click="pick(item)"
      >
        {{ item }}
      </button>
    </div>

    <div class="composer__box">
      <textarea
        ref="textarea"
        v-model="model"
        class="textarea composer__input"
        rows="1"
        placeholder="输入你的问题，Enter 发送 / Shift + Enter 换行"
        :disabled="disabled"
        @keydown="onKeydown"
        @input="autoGrow"
      />

      <div class="composer__footer">
        <label class="row composer__topk">
          <span class="field__label">Top-K</span>
          <select
            class="select composer__select"
            :value="topK"
            :disabled="streaming"
            @change="emit('update:topK', Number($event.target.value))"
          >
            <option v-for="k in [1, 2, 3, 5, 8]" :key="k" :value="k">{{ k }}</option>
          </select>
        </label>

        <span class="composer__hint faint">回答仅依据知识库材料，并标注引用出处</span>

        <button v-if="streaming" class="btn btn--danger btn--sm" type="button" @click="emit('stop')">
          停止生成
        </button>
        <button
          v-else
          class="btn btn--primary btn--sm"
          type="button"
          :disabled="disabled || !model.trim()"
          @click="submit"
        >
          发送
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.composer { display: flex; flex-direction: column; gap: var(--space-2); }

.composer__suggestions { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  padding: 5px 11px; border-radius: 999px; border: 1px solid var(--c-border-strong);
  background: var(--c-surface); color: var(--c-text-muted); font-size: 12px; font-family: inherit;
  cursor: pointer; transition: background .15s, color .15s, border-color .15s;
}
.chip:hover:not(:disabled) { background: var(--c-primary-soft); border-color: #cdd8fb; color: var(--c-primary-strong); }
.chip:disabled { opacity: .5; cursor: not-allowed; }

.composer__box {
  border: 1px solid var(--c-border-strong); border-radius: var(--radius);
  background: var(--c-surface); box-shadow: var(--shadow-sm); overflow: hidden;
}
.composer__box:focus-within { border-color: var(--c-primary); box-shadow: 0 0 0 3px var(--c-primary-soft); }

.composer__input { border: none; border-radius: 0; box-shadow: none !important; min-height: 46px; padding: 12px 14px; }
.composer__input:focus { box-shadow: none; }

.composer__footer {
  display: flex; align-items: center; gap: var(--space-3);
  padding: 8px 12px; border-top: 1px solid var(--c-border); background: var(--c-surface-alt);
}
.composer__topk { gap: 6px; }
.composer__select { width: auto; padding: 3px 8px; font-size: 12px; }
.composer__hint { font-size: 11px; flex: 1; }

@media (max-width: 720px) {
  .composer__hint { display: none; }
}
</style>