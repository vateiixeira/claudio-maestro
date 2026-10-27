<script setup lang="ts">
import type { WorkPrPage } from '../../types/work'
defineProps<{ page: WorkPrPage }>()
const count = (n: number, singular: string, plural: string) => `${n} ${n === 1 ? singular : plural}`
const title = (url: string) => { try { return new URL(url).pathname.replace(/^\//, '') } catch { return url } }
</script>
<template>
  <section class="work-section" aria-label="Pull requests da tarefa">
    <div class="work-section-header"><h2>Pull requests</h2><span class="work-muted">{{ page.items.length }} de {{ page.total }}</span></div>
    <article v-for="pr in page.items" :key="pr.url" class="task-pr">
      <div class="pr-heading"><a :href="pr.url" target="_blank" rel="noopener noreferrer" class="work-link">{{ title(pr.url) }} ↗</a><span class="work-muted">{{ pr.closed ? 'Fechado' : 'Aberto' }}</span></div>
      <p class="work-muted">Aberto na tentativa <a class="work-link" :href="`#attempt-${pr.origin_attempt_id}`">#{{ pr.origin_attempt_id }}</a><template v-if="pr.last_attempt_id !== pr.origin_attempt_id">. Último registro na tentativa <a class="work-link" :href="`#attempt-${pr.last_attempt_id}`">#{{ pr.last_attempt_id }}</a></template>.</p>
      <ul v-if="Object.values(pr.comments).some(Boolean)" class="pr-feedback work-muted">
        <li v-if="pr.comments.queued">{{ count(pr.comments.queued, 'comentário na fila', 'comentários na fila') }}</li>
        <li v-if="pr.comments.dispatching">{{ count(pr.comments.dispatching, 'comentário em envio', 'comentários em envio') }}</li>
        <li v-if="pr.comments.delivered">{{ count(pr.comments.delivered, 'comentário entregue ao executor', 'comentários entregues ao executor') }}</li>
        <li v-if="pr.comments.uncertain" class="pr-uncertain">{{ count(pr.comments.uncertain, 'envio incerto', 'envios incertos') }}, aguardando conciliação</li>
      </ul>
      <p v-if="pr.latest_feedback_attempt_id" class="work-muted">Continuidade dos comentários: tentativa <a class="work-link" :href="`#attempt-${pr.latest_feedback_attempt_id}`">#{{ pr.latest_feedback_attempt_id }}</a>.</p>
    </article>
    <p v-if="page.total > page.items.length" class="work-muted">Mostrando os {{ page.items.length }} registros mais recentes. O histórico das tentativas conserva a proveniência anterior.</p>
  </section>
</template>
<style scoped>
.task-pr{border-top:1px solid var(--color-line);padding:15px 0;font-size:0.8125rem}.pr-heading{display:flex;gap:12px;align-items:baseline;justify-content:space-between}.pr-heading a{overflow-wrap:anywhere;min-width:0}.pr-feedback{padding-left:18px;line-height:1.8}.pr-uncertain{color:var(--color-secondary-soft)}
</style>
