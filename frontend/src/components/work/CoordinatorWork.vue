<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useEventSocket } from '../../api/socket'
import { errorMessage, request } from '../../api/http'
import { useWorkStore } from '../../stores/work'
import type { WorkDetail, WorkDecision, WorkNotice } from '../../types/work'
import TaskRow from './TaskRow.vue'
import AttemptResult from './AttemptResult.vue'
import DecisionRequest from './DecisionRequest.vue'
const props = defineProps<{ projectId: number }>()
const work = useWorkStore(), socket = useEventSocket()
const rows = ref<WorkDetail[]>([]), decisions = ref<WorkDecision[]>([]), notices = ref<WorkNotice[]>([])
const error = ref(''), loading = ref(true), limit = ref(12), total = ref(0)
let ticket = 0
async function load() {
  const mine = ++ticket, projectId = props.projectId; error.value = ''
  try {
    const [page, pending, feed] = await Promise.all([work.list({ project_id: projectId, limit: limit.value, offset: 0 }), work.decisions(projectId), work.feed(projectId)])
    const details = await Promise.all(page.items.map(item => work.loadDetail(item.id)))
    if (mine !== ticket) return
    rows.value = details; total.value = page.total; decisions.value = pending.items; notices.value = feed.items
    if (feed.after) void request('POST', `/api/projects/${projectId}/work-feed/seen`, { through: feed.after }).catch(() => {})
  } catch (e) { if (mine === ticket) error.value = errorMessage(e) }
  finally { if (mine === ticket) loading.value = false }
}
watch(() => [props.projectId, work.changeVersion], () => { rows.value = props.projectId === rows.value[0]?.item.project_id ? rows.value : []; void load() }, { immediate: true })
const off = socket.onOpen(() => { void load() })
onBeforeUnmount(() => { ticket++; off() })
function more() { limit.value = Math.min(limit.value + 12, 200); void load() }
</script>
<template>
  <section class="coordinator-work" aria-label="Trabalho coordenado neste projeto" data-test="coordinator-work">
    <div class="work-section-header"><h2>Trabalho do projeto</h2><RouterLink class="work-link" :to="`/tarefas?project=${projectId}`">Todas as tarefas ↗</RouterLink></div>
    <p v-if="error" role="alert" class="work-error">{{ error }} <button class="work-button" type="button" @click="load">Tentar novamente</button></p>
    <div v-if="loading && !rows.length" class="work-skeleton" role="status"><span class="sr-only">Carregando execuções…</span><span /><span /></div>
    <DecisionRequest v-for="decision in decisions" :key="decision.id" :decision="decision" @answered="load" @stale="load" />
    <p v-if="!loading && !rows.length && !error" class="work-muted">As tarefas delegadas pelo CTO aparecerão aqui, com o andamento e o resultado de cada tentativa. Continue conversando abaixo.</p>
    <article v-for="detail in rows" :key="detail.item.id" class="coordinator-task"><TaskRow :item="detail.item" /><AttemptResult v-for="attempt in detail.attempts" :key="attempt.id" :attempt="attempt" live /></article>
    <button v-if="total > rows.length && limit < 200" class="work-button" type="button" @click="more">Mostrar tarefas anteriores</button>
    <details v-if="notices.length" class="coordinator-feed"><summary>Avisos ao CTO</summary><ul><li v-for="notice in notices" :key="notice.id"><span>{{ notice.summary }}</span><span class="work-muted">{{ notice.dispatch_state === 'uncertain' ? 'Entrega incerta, aguardando conciliação' : notice.dispatch_state === 'sent' ? 'Enviado ao CTO' : notice.dispatch_state === 'unsent' ? 'Não enviado ao CTO' : 'Aguardando entrega ao CTO' }}</span></li></ul></details>
  </section>
</template>
<style scoped>
.coordinator-work{min-width:0;margin:24px 0 16px;padding-top:22px;border-top:1px solid var(--color-line)}.coordinator-task{margin:16px 0 22px}.coordinator-task :deep(.work-row){grid-template-columns:minmax(0,1fr) 120px;padding:10px 2px;border:0}.coordinator-task :deep(.work-row-project){display:none}.coordinator-feed{font-size:0.75rem;color:var(--color-fg-muted);margin-top:18px}.coordinator-feed summary{cursor:pointer}.coordinator-feed ul{padding:0;list-style:none}.coordinator-feed li{display:flex;flex-direction:column;gap:5px;padding:10px 0;border-top:1px solid var(--color-line)}
</style>
