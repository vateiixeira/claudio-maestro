<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { useEventSocket } from '../../api/socket'
import { errorMessage, request } from '../../api/http'
import { useWorkStore } from '../../stores/work'
import type { WorkAttention, WorkOverview } from '../../types/work'
const props = defineProps<{ projectId: number }>()
const work = useWorkStore(), socket = useEventSocket()
const expanded = ref(false), mobileDetailsOpen = ref(false)
const overview = ref<WorkOverview | null>(null), error = ref(''), loading = ref(true)
let ticket = 0
async function load() {
  const mine = ++ticket, projectId = props.projectId
  error.value = ''; loading.value = true
  try {
    const page = await request<WorkOverview>('GET', `/api/projects/${projectId}/work-overview?limit=50&offset=0`)
    if (mine === ticket) overview.value = page
  } catch (e) { if (mine === ticket) error.value = errorMessage(e) }
  finally { if (mine === ticket) loading.value = false }
}
watch(() => [props.projectId, work.changeVersion], (_value, before) => { if (!before || props.projectId !== before[0]) { overview.value = null; expanded.value = false }; void load() }, { immediate: true })
const off = socket.onOpen(() => { void load() })
onBeforeUnmount(() => { ticket++; off() })
const needsAction = computed(() => ['decision', 'permission', 'continuation'].reduce((sum, kind) => sum + (overview.value?.counts[kind as keyof WorkOverview['counts']] ?? 0), 0))
const actionKinds = new Set(['decision', 'permission', 'continuation'])
const actionItems = computed(() => overview.value?.items.filter(item => actionKinds.has(item.kind)) ?? [])
const relevant = computed(() => { const items = overview.value?.items ?? []; return [...(expanded.value ? actionItems.value : actionItems.value.slice(0, 3)), ...items.filter(item => item.kind !== 'inactive' && !actionKinds.has(item.kind)).slice(0, 3)] })
function explanation(item: WorkAttention) {
  if (item.kind === 'queued') {
    if (item.queue_reason?.blocker_title) return `Na fila, aguardando ${item.queue_reason.blocker_title}`
    return item.queue_reason ? { global_capacity: 'Na fila, aguardando capacidade global', project_capacity: 'Na fila, aguardando capacidade do projeto', resource: 'Na fila, aguardando recurso ocupado', dependency: 'Na fila, aguardando dependência' }[item.queue_reason.kind] : 'Na fila, aguardando início'
  }
  return { decision: 'Decisão registrada aguardando sua resposta', permission: 'Pedido pendente na execução', continuation: 'Parou sem registrar uma entrega. Leia a última resposta e oriente a continuação.', running: 'Em execução', waiting: 'Aguardando próximo passo da execução', uncertain: 'Envio incerto. Aguarde a conciliação antes de repetir uma mensagem.', paused: 'Trabalho pausado', inactive: 'Sem ação pendente' }[item.kind]
}
const target = (item: WorkAttention) => item.kind === 'permission' && item.session_id ? `/sessions/${item.session_id}` : `/tarefas/${item.work_item_id}${item.attempt_id ? `#attempt-${item.attempt_id}` : ''}`
</script>
<template>
  <section class="coordinator-attention" aria-label="Próximo passo do projeto" data-test="coordinator-attention" :class="{ 'mobile-expanded': mobileDetailsOpen, 'has-action': actionItems.length > 0 }">
    <div class="attention-heading"><h2>{{ needsAction ? 'O que precisa de você' : 'Próximo passo' }}<span v-if="needsAction" class="mobile-attention-count"> ({{ needsAction }})</span></h2><button type="button" data-test="attention-details-toggle" :aria-expanded="mobileDetailsOpen" class="attention-details-toggle" @click="mobileDetailsOpen = !mobileDetailsOpen">{{ mobileDetailsOpen ? 'Recolher' : 'Ver próximos passos' }}</button></div>
    <p v-if="loading && !overview" role="status" class="work-muted">Conferindo o andamento do projeto…</p>
    <p v-if="error" role="alert" class="work-error">{{ error }} <button type="button" class="work-button" @click="load">Tentar novamente</button></p>
    <template v-if="overview">
      <p v-if="needsAction" class="attention-count work-muted">{{ needsAction }} {{ needsAction === 1 ? 'pedido aguarda sua resposta ou orientação.' : 'pedidos aguardam sua resposta ou orientação.' }}</p>
      <p v-if="!needsAction" class="attention-no-action work-muted">Nenhuma ação pendente para você.</p>
      <ul class="attention-list">
        <li v-for="item in relevant" :key="item.work_item_id">
          <div class="attention-description"><RouterLink class="work-link attention-title" :to="target(item)">{{ item.title }}</RouterLink><p>{{ explanation(item) }}</p></div>
          <RouterLink v-if="item.kind === 'continuation' && item.can_continue" data-test="continue-work" class="work-button work-primary" :to="target(item)">Orientar execução</RouterLink>
          <RouterLink v-else-if="item.kind === 'decision' || item.kind === 'permission'" class="work-button" :to="target(item)">{{ item.kind === 'decision' ? 'Responder decisão' : 'Responder na conversa' }}</RouterLink>
        </li>
      </ul>
      <button v-if="!expanded && actionItems.length > 3" data-test="more-attention" type="button" class="work-button" @click="expanded = true">Ver outros {{ actionItems.length - 3 }} pedidos</button>
      <RouterLink v-if="overview.total > relevant.length" class="attention-all-tasks work-link" :to="`/tarefas?project=${projectId}`">Ver todas as {{ overview.total }} tarefas ↗</RouterLink>
    </template>
  </section>
</template>
<style scoped>
.coordinator-attention{min-width:0;padding:2px 0 18px;border-bottom:1px solid var(--color-line)}h2{margin:0 0 12px;font-size:0.9375rem;font-weight:600;color:var(--color-fg)}.attention-list{margin:0;padding:0;list-style:none}.attention-list li{display:flex;align-items:center;gap:16px;padding:12px 0}.attention-description{min-width:0;flex:1}.attention-title{font-size:0.8125rem;overflow-wrap:anywhere}.attention-description p{margin:5px 0 0;font-size:0.75rem;line-height:1.65;color:var(--color-fg-muted);max-width:70ch}.attention-list .work-button{flex-shrink:0}@media(max-width:600px),(max-height:760px){.attention-list li{align-items:flex-start;flex-direction:column;gap:10px}}
.attention-heading{display:flex;align-items:center;justify-content:space-between;gap:8px}.attention-details-toggle,.mobile-attention-count{display:none}
@media(max-width:600px),(max-height:760px){
.coordinator-attention{padding-bottom:8px}.attention-heading h2{margin-bottom:4px;font-size:0.8125rem}.attention-details-toggle{display:block;flex-shrink:0;border:0;background:transparent;color:var(--color-info-soft);font:inherit;font-size:0.6875rem;min-height:28px;cursor:pointer}.attention-details-toggle:focus-visible{outline:2px solid var(--color-primary);outline-offset:2px}.mobile-attention-count{display:inline}
.coordinator-attention:not(.mobile-expanded) .attention-count,.coordinator-attention:not(.mobile-expanded) .attention-description p,.coordinator-attention:not(.mobile-expanded) .attention-all-tasks,.coordinator-attention:not(.mobile-expanded) [data-test=more-attention]{display:none}
.coordinator-attention:not(.mobile-expanded) .attention-list li:not(:first-child),.coordinator-attention:not(.mobile-expanded):not(.has-action) .attention-list{display:none}
.coordinator-attention:not(.mobile-expanded) .attention-list li{flex-direction:row;align-items:center;gap:8px;padding:6px 0}.coordinator-attention:not(.mobile-expanded) .attention-title{font-size:0.75rem}.coordinator-attention:not(.mobile-expanded) .work-button{font-size:0.6875rem;padding:6px 8px;min-height:32px}.attention-no-action{margin:2px 0 4px;font-size:0.6875rem}
}
</style>
