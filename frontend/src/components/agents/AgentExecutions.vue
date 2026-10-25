<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { errorMessage, listAnnouncements } from '../../api/http'
import { useEventSocket } from '../../api/socket'
import { useSpecialistsStore } from '../../stores/specialists'
import AgentExecutionCard from './AgentExecutionCard.vue'
import type { Announcement, SpecialistRun } from '../../types/api'
const props = defineProps<{ agentId: number; mainSessionId: string }>()
const emit = defineEmits<{ reveal: [] }>()
const store = useSpecialistsStore()
const socket = useEventSocket()
const error = ref<string | null>(null)
const shown = ref(5)
const loading = ref(true)
const announcements = ref<Announcement[]>([])
let ticket = 0
async function load() {
  const mine = ++ticket
  const id = props.agentId
  const [runsResult, announcementsResult] = await Promise.allSettled([store.loadRuns(id), listAnnouncements(id)])
  if (mine !== ticket) return
  if (announcementsResult.status === 'fulfilled') announcements.value = announcementsResult.value
  const failed = runsResult.status === 'rejected' ? runsResult : announcementsResult.status === 'rejected' ? announcementsResult : null
  error.value = failed ? errorMessage(failed.reason) : null
  loading.value = false
}
watch(() => props.agentId, () => { shown.value = 5; announcements.value = []; loading.value = true; void load() }, { immediate: true })
watch(() => store.changes[props.agentId], () => { void load() })
const offOpen = socket.onOpen(() => { void load() })
onBeforeUnmount(() => { ticket++; offOpen() })
const runs = computed(() => store.runsOf(props.agentId).filter(run => !run.message && run.session_id !== props.mainSessionId))
// Every in-progress run stays visible; older rounds can be opened without changing the parent's route.
const currentRound = (run: SpecialistRun) => !!run.session_id && runs.value.find(other => other.session_id === run.session_id)?.id === run.id
const rank = (outcome: string) => outcome === 'running' || outcome === 'starting' ? 2 : outcome === 'waiting' ? 1 : 0
const visibleRuns = computed(() => runs.value
  .filter((run, i) => i < shown.value || rank(run.outcome) > 0)
  .slice().sort((a, b) => rank(a.outcome) - rank(b.outcome) || a.started_at - b.started_at || a.id - b.id))
</script>
<template>
  <section data-test="agent-executions" aria-label="Execuções nesta conversa" class="agent-executions">
    <header><h2>Execuções do agente</h2><p>Uma conversa contínua. Cada rodada tem seu próprio andamento e resultado.</p></header>
    <p v-if="error" role="alert" class="execution-error">Não foi possível carregar as execuções. {{ error }} <button type="button" class="underline" @click="load">Tentar novamente</button></p>
    <p v-if="loading && !runs.length" role="status" class="execution-empty">Carregando execuções…</p>
    <p v-else-if="!runs.length && !error" class="execution-empty">As execuções aparecerão aqui quando o agente rodar. Você pode continuar conversando abaixo.</p>
    <button v-if="runs.length > visibleRuns.length" type="button" data-test="agent-executions-more" class="execution-more" @click="shown += 5">Mostrar execuções anteriores</button>
    <AgentExecutionCard v-for="run in visibleRuns" :key="run.id" :run="run" :live="rank(run.outcome) > 0 && currentRound(run)" :result="announcements.find(item => item.run_id === run.id)" @reveal="emit('reveal')" />
  </section>
</template>
<style scoped>
.agent-executions { display:flex; min-width:0; flex-direction:column; gap:10px; margin-top:8px; }
header { margin-bottom:5px; }
h2 { margin:0; color:var(--color-fg); font-size:14px; font-weight:500; }
header p { margin:6px 0 0; color:var(--color-fg-subtle); font-size:12px; line-height:1.7; }
.execution-empty,.execution-error { margin:0; padding:16px 0; color:var(--color-fg-subtle); font-size:12px; line-height:1.7; }
.execution-error { color:var(--color-diff-del-fg); }
.execution-more { width:fit-content; cursor:pointer; border:0; border-radius:4px; padding:6px 0; background:transparent; color:var(--color-fg-muted); font-size:12px; text-decoration:underline; text-underline-offset:3px; }
.execution-more:focus-visible { outline:2px solid var(--color-primary); outline-offset:3px; }
</style>
