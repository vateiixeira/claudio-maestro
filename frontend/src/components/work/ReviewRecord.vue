<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ review: Record<string, unknown> }>()
const states: Record<string, string> = { queued: 'Na fila', reviewing: 'Em revisão', approved: 'Aprovada', returned: 'Devolvida ao executor', stale: 'Desatualizada', blocked: 'Bloqueada' }
const status = computed(() => states[String(props.review.status)] ?? 'Parecer registrado')
</script>
<template>
  <article class="review-record">
    <h3>Revisão #{{ review.id }} <span>{{ status }}</span></h3>
    <p class="work-muted">Entrega da tentativa <a class="work-link" :href="`#attempt-${review.author_attempt_id}`">#{{ review.author_attempt_id }}</a><template v-if="review.review_attempt_id">, examinada na tentativa <a class="work-link" :href="`#attempt-${review.review_attempt_id}`">#{{ review.review_attempt_id }}</a></template>. Entrada da tarefa: revisão {{ review.input_revision }}.</p>
    <p v-if="review.reason" class="work-prose">{{ review.reason }}</p>
  </article>
</template>
<style scoped>
.review-record{padding:16px 0;border-top:1px solid var(--color-line)}h3{display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px;font-size:0.8125rem;font-weight:500;margin:0 0 8px}h3 span{font-size:0.75rem;font-weight:400;color:var(--color-fg-subtle)}
</style>
