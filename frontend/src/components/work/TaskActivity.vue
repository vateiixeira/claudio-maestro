<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import type { WorkEvent, WorkEventCursor } from '../../types/work'
import { useWorkStore } from '../../stores/work'
import { errorMessage } from '../../api/http'
import IconCircle from '../icons/IconCircle.vue'
const props = defineProps<{ itemId: number; events: WorkEvent[]; page?: WorkEventCursor }>()
const work = useWorkStore()
const entries = ref<WorkEvent[]>([]), before = ref<number | null>(null), hasMore = ref(false)
const busy = ref(false), error = ref(''), historyLoaded = ref(false)
let currentId: number | null = null, ticket = 0
function merge(events: WorkEvent[]) {
  entries.value = [...new Map([...entries.value, ...events].map(event => [event.id, event])).values()].sort((a, b) => a.id - b.id)
}
watch(() => [props.itemId, props.events, props.page], () => {
  if (props.itemId !== currentId) { ticket++; currentId = props.itemId; entries.value = []; busy.value = false; historyLoaded.value = false; error.value = '' }
  merge(props.events)
  // The head can move while disconnected. Restart traversal from that head,
  // retaining loaded history; this also makes any intervening gap accessible.
  before.value = props.page?.before ?? null
  hasMore.value = props.page?.has_more ?? false
}, { immediate: true })
async function older() {
  if (busy.value || !hasMore.value || before.value === null) return
  const id = props.itemId, cursor = before.value, mine = ++ticket
  busy.value = true; error.value = ''
  try {
    const page = await work.eventPage(id, cursor)
    if (mine !== ticket || id !== props.itemId) return
    merge(page.items); historyLoaded.value = true
    if (before.value === cursor) { before.value = page.before; hasMore.value = page.has_more }
  } catch (e) { if (mine === ticket) error.value = errorMessage(e) }
  finally { if (mine === ticket) busy.value = false }
}
onBeforeUnmount(() => ticket++)
const when = (timestamp: number) => new Date(timestamp * 1000).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
const eventLabels: Record<string,string> = { item_created: 'Tarefa criada', item_updated: 'Tarefa atualizada', item_blocked: 'Tarefa bloqueada', attempt_claimed: 'Execução reservada', attempt_dispatching: 'Envio reservado', attempt_running: 'Execução iniciada', attempt_waiting: 'Aguardando continuidade', attempt_uncertain: 'Envio incerto', attempt_result_recorded: 'Entrega registrada', attempt_finished: 'Execução encerrada', review_prepared: 'Revisão preparada', review_resolved: 'Parecer registrado', review_stale: 'Revisão desatualizada', decision_requested: 'Decisão humana pendente', decision_answered: 'Decisão respondida', decision_expired: 'Decisão expirada', dependency_added: 'Dependência vinculada', attempt_continuation_reserved: 'Continuidade reservada', attempt_continuation_unsent: 'Continuidade não enviada', collection_published: 'Coleta publicada', created: 'Tarefa criada', started: 'Execução iniciada', result: 'Entrega registrada', updated: 'Tarefa atualizada', status: 'Estado atualizado', review: 'Revisão registrada', decision: 'Decisão solicitada' }
</script>
<template>
  <section class="work-section" aria-label="Atividade da tarefa" data-test="work-activity">
    <div class="work-section-header"><h2>Atividade</h2></div>
    <p class="work-muted">{{ historyLoaded ? 'Atividades recentes e histórico carregado.' : 'Atividades recentes.' }} Até {{ page?.limit ?? 50 }} por página.</p>
    <button v-if="hasMore" type="button" class="work-button" :disabled="busy" @click="older">{{ busy ? 'Carregando atividades…' : 'Carregar atividades anteriores' }}</button>
    <p v-if="error" role="alert" class="work-error">{{ error }} Tente carregar as atividades anteriores novamente.</p>
    <ol class="work-timeline"><li v-for="event in entries" :key="event.id" :data-event-id="event.id"><IconCircle :size="12" class="text-fg-subtle mt-1" /><span>{{ eventLabels[event.kind] ?? 'Atividade registrada' }}<span class="block work-muted">{{ event.actor }}</span><details v-if="Object.keys(event.data ?? {}).length"><summary>Ver registro</summary><pre>{{ JSON.stringify(event.data, null, 2) }}</pre></details></span><time>{{ when(event.created_at) }}</time></li></ol>
  </section>
</template>
<style scoped>
summary{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:0.6875rem;max-height:340px;overflow:auto;line-height:1.7}
</style>
