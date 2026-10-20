<script setup>
/**
 * 三态反馈组件（FR-E4）：加载中 / 空数据 / 请求失败。
 * 页面只需要给出文案，样式与图标在这里统一。
 */
defineProps({
  type: { type: String, default: 'empty' }, // loading | empty | error
  title: { type: String, default: '' },
  hint: { type: String, default: '' },
  actionLabel: { type: String, default: '' },
})
defineEmits(['retry'])

const ICONS = { loading: '', empty: '🗂', error: '⚠️' }
const DEFAULT_TITLES = { loading: '加载中…', empty: '暂无数据', error: '加载失败' }
</script>

<template>
  <div class="state" :class="`state--${type}`">
    <span v-if="type === 'loading'" class="spinner" role="status" aria-label="加载中" />
    <span v-else class="state__icon">{{ ICONS[type] || ICONS.empty }}</span>

    <p class="state__title">{{ title || DEFAULT_TITLES[type] }}</p>
    <p v-if="hint" class="state__hint">{{ hint }}</p>

    <button v-if="actionLabel" class="btn btn--sm" @click="$emit('retry')">{{ actionLabel }}</button>
  </div>
</template>