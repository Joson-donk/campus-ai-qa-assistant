<script setup>
/** 命中的原文片段列表（FR-E2：可展开的「参考原文」）。 */
defineProps({
  hits: { type: Array, default: () => [] },
  threshold: { type: Number, default: 0 },
})

function scoreClass(score) {
  if (score >= 0.6) return 'badge--success'
  if (score >= 0.4) return 'badge--primary'
  return 'badge--warning'
}
</script>

<template>
  <div v-if="hits.length" class="sources">
    <p class="sources__title">
      参考原文
      <span class="faint">（{{ hits.length }} 条，相似度阈值 {{ threshold.toFixed(2) }}）</span>
    </p>

    <ol class="sources__list">
      <!-- FR-E5：v-for 必须带唯一 key，这里用向量库中的块 ID -->
      <li v-for="hit in hits" :key="hit.id" class="source">
        <div class="source__head">
          <span class="source__index">【{{ hit.index }}】</span>
          <span class="source__name" :title="hit.source">{{ hit.source }}</span>
          <span v-if="hit.page" class="badge">{{ hit.page }}</span>
          <span class="badge" :class="scoreClass(hit.score)">相似度 {{ hit.score.toFixed(4) }}</span>
        </div>
        <p class="source__text">{{ hit.text }}</p>
        <p class="source__meta mono">chunk {{ hit.chunk_index }} · {{ hit.id }}</p>
      </li>
    </ol>
  </div>

  <p v-else class="sources__empty faint">本次回答没有引用任何原文片段。</p>
</template>

<style scoped>
.sources { display: flex; flex-direction: column; gap: var(--space-2); }
.sources__title { font-size: 12px; color: var(--c-text-muted); font-weight: 500; }
.sources__list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--space-2); }
.sources__empty { font-size: 12px; }

.source {
  border: 1px solid var(--c-border);
  border-left: 3px solid var(--c-primary);
  border-radius: var(--radius-sm);
  background: var(--c-surface-alt);
  padding: var(--space-2) var(--space-3);
}
.source__head { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; font-size: 12px; }
.source__index { color: var(--c-primary-strong); font-weight: 600; }
.source__name { font-weight: 500; color: var(--c-text); }
.source__text {
  margin-top: 6px; font-size: 12.5px; color: var(--c-text-muted);
  white-space: pre-wrap; word-break: break-word;
  max-height: 132px; overflow-y: auto;
}
.source__meta { margin-top: 6px; color: var(--c-text-faint); font-size: 11px; }
</style>