<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { formatRunDate } from '../../agents'
import { openSpecialistConversation, errorMessage } from '../../api/http'
import { useSpecialistsStore } from '../../stores/specialists'
import IconArrowUp from '../icons/IconArrowUp.vue'
import AgentRunIcon from './AgentRunIcon.vue'
import { BTN_SMALL, ERROR } from './styles'

const props = defineProps<{ agentId: number }>()
const store = useSpecialistsStore()
const router = useRouter()
const continuing = ref(false)
const filter = ref<'all' | 'problems'>('all')
const pending = computed(() => store.runsOf(props.agentId).filter(run => ['queued', 'starting'].includes(run.outcome)))
const history = computed(() => store.runsOf(props.agentId).filter(run => !['queued', 'starting'].includes(run.outcome)))
const visibleHistory = computed(() => history.value.filter(run => filter.value === 'all' || ['failed', 'waiting', 'missed'].includes(run.outcome)))
const groups = computed(() => [{ label: 'Fila de execução', runs: pending.value, queue: true }, { label: 'Histórico de execuções', runs: visibleHistory.value, queue: false }])
async function continueRun(sessionId: string) {
  if (continuing.value) return
  continuing.value = true
  error.value = null
  try {
    const chat = await openSpecialistConversation(props.agentId, { session_id: sessionId })
    await router.push({ name: 'session', params: { id: chat.session_id } })
  } catch (e) { error.value = errorMessage(e) }
  finally { continuing.value = false }
}
const error = ref<string | null>(null)
const cancelling = ref(new Set<number>())

async function cancel(runId: number): Promise<void> {
  if (cancelling.value.has(runId)) return
  cancelling.value.add(runId)
  error.value = null
  try {
    await store.cancelRun(props.agentId, runId)
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    cancelling.value.delete(runId)
  }
}

async function load(): Promise<void> {
  try {
    await store.loadRuns(props.agentId)
    error.value = null
  } catch (e) {
    error.value = errorMessage(e)
  }
}
onMounted(load)
watch(() => store.changes[props.agentId], () => { void load() })
</script>

<template>
  <div class="agent-runs">
    <p v-if="error" data-test="runs-error" role="alert" :class="ERROR">{{ error }}</p>
    <section v-for="group in groups" :key="group.label" :aria-label="group.label" class="run-group">
      <header class="run-group-heading"><div><h3>{{ group.label }} <span class="run-count">{{ group.queue ? pending.length : history.length }}</span></h3><p>{{ group.queue ? 'Pedidos que aguardam sua vez de executar.' : 'As últimas 50 execuções e seus resultados.' }}</p></div><div v-if="!group.queue" class="run-filters" aria-label="Filtrar histórico"><button type="button" data-test="run-filter-all" :aria-pressed="filter === 'all'" @click="filter = 'all'">Todas</button><button type="button" data-test="run-filter-problems" :aria-pressed="filter === 'problems'" @click="filter = 'problems'">Problemas</button></div></header>
      <p v-if="!group.runs.length" class="run-empty">{{ group.queue ? 'Nenhum pedido na fila.' : history.length ? 'Nenhum problema no histórico.' : 'Ainda não rodou.' }}</p>
      <ul v-else class="run-list"><li v-for="run in group.runs" :key="run.id" data-test="run-row" class="run-row">
        <div class="run-status"><AgentRunIcon :outcome="run.outcome" :size="14" show-label /></div>
        <div class="run-description"><span class="run-trigger">{{ run.message ? 'Mensagem' : run.trigger === 'schedule' ? 'Horário' : run.trigger === 'comment' ? 'Comentário de PR' : 'Manual' }}</span><p v-if="run.reason">{{ run.reason }}</p></div>
        <time class="run-date">{{ formatRunDate(run.started_at) }}</time>
        <div class="run-actions"><RouterLink v-if="run.session_id" :to="{ name: 'session', params: { id: run.session_id } }">Abrir<span class="sr-only"> conversa</span><IconArrowUp :size="12" class="rotate-45" /></RouterLink><button v-if="run.session_id && run.outcome !== 'queued' && run.outcome !== 'starting'" type="button" data-test="run-continue" :class="BTN_SMALL" :disabled="continuing" @click="continueRun(run.session_id)">Continuar</button><button v-if="run.outcome === 'queued'" type="button" data-test="run-cancel" :class="BTN_SMALL" :disabled="cancelling.has(run.id)" @click="cancel(run.id)">{{ cancelling.has(run.id) ? 'Cancelando…' : 'Cancelar' }}</button></div>
      </li></ul>
    </section>
  </div>
</template>
<style scoped>
.agent-runs { padding:28px 0 48px; }
.run-group+.run-group { margin-top:36px; }
.run-group-heading { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:18px; }
h3 { display:flex; align-items:center; gap:10px; margin:0; font-size:15px; font-weight:500; letter-spacing:-.015em; }
.run-count { border:1px solid var(--color-line); border-radius:5px; padding:1px 5px; color:var(--color-fg-subtle); font-family:var(--font-mono); font-size:10px; }
.run-group-heading p { margin:6px 0 0; color:var(--color-fg-subtle); font-size:12px; }
.run-filters { display:flex; flex-shrink:0; gap:2px; border:1px solid var(--color-line); border-radius:7px; padding:3px; }
.run-filters button { border:0; border-radius:4px; padding:6px 10px; background:transparent; color:var(--color-fg-subtle); font-size:11px; cursor:pointer; }
.run-filters button[aria-pressed=true] { background:var(--color-card); color:var(--color-fg); }
.run-filters button:focus-visible { outline:2px solid var(--color-primary); outline-offset:2px; }
.run-list { margin:0; padding:0; list-style:none; }
.run-row { display:grid; grid-template-columns:125px minmax(0,1fr) 120px auto; align-items:start; gap:18px; border-top:1px solid var(--color-line); padding:18px 0; font-size:12px; }
.run-status { padding-top:2px; font-size:11px; }
.run-trigger { color:var(--color-fg); font-weight:500; }
.run-description p { margin:6px 0 0; color:var(--color-fg-muted); line-height:1.7; overflow-wrap:anywhere; }
.run-date { padding-top:3px; font-family:var(--font-mono); color:var(--color-fg-subtle); font-size:10px; line-height:1.7; }
.run-actions { display:flex; align-items:center; justify-content:flex-end; flex-wrap:wrap; gap:12px; }
.run-actions a { display:inline-flex; align-items:center; gap:4px; color:var(--color-fg-muted); font-size:11px; text-decoration:none; padding:5px 0; }
.run-actions a:hover { color:var(--color-fg); }
.run-empty { margin:0; border-top:1px solid var(--color-line); padding:24px 0; color:var(--color-fg-subtle); font-size:12px; }
@container (max-width:850px) { .run-row { grid-template-columns:115px minmax(0,1fr) auto; } .run-date { grid-column:2; grid-row:2; } .run-actions { grid-column:3; grid-row:1 / 3; } }
@container (max-width:500px) { .run-group-heading { align-items:flex-start; flex-direction:column; } .run-row { grid-template-columns:minmax(0,1fr) auto; gap:10px 14px; } .run-status { grid-column:1; } .run-description { grid-column:1 / -1; grid-row:2; } .run-date { grid-column:1; grid-row:3; } .run-actions { grid-column:2; grid-row:1; } }
</style>
