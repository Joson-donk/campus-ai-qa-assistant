<script setup>
/** 统计数字卡片（FR-E3）。 */
defineProps({
  items: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
})
</script>

<template>
  <div class="grid-stats">
    <article v-for="item in items" :key="item.label" class="stat card">
      <p class="stat__label">{{ item.label }}</p>
      <p class="stat__value">
        <span v-if="loading" class="spinner" />
        <template v-else>{{ item.value }}</template>
      </p>
      <p v-if="item.hint" class="stat__hint faint">{{ item.hint }}</p>
    </article>
  </div>
</template>

<style scoped>
.stat { padding: var(--space-4); display: flex; flex-direction: column; gap: 4px; }
.stat__label { font-size: 12px; color: var(--c-text-muted); }
.stat__value { font-size: 24px; font-weight: 600; font-variant-numeric: tabular-nums; line-height: 1.2; }
.stat__hint { font-size: 11px; }
</style>