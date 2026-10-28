<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { errorMessage } from '../../api/http'
import { useOrgStore } from '../../stores/org'
import AgentRunRow from '../org/agent/AgentRunRow.vue'

// Below the main conversation of an agent: its runs in flight and the latest ones, each with its result. The whole
// list, with the queue, lives in the agent's panel.
const props = defineProps<{ agentId: number; mainSessionId: string }>()
const org = useOrgStore()
const SHOWN = 5
const error = ref<string | null>(null)
const loading = ref(true)
let ticket = 0

async function load() {
  const mine = ++ticket
  try {
    await org.loadRuns(props.agentId)
    if (mine === ticket) error.value = null
  } catch (e) {
    if (mine === ticket) error.value = errorMessage(e)
  } finally {
    if (mine === ticket) loading.value = false
  }
}
watch(() => props.agentId, () => { loading.value = true; void load() }, { immediate: true })
watch(() => org.changes[props.agentId], () => { void load() })
onBeforeUnmount(() => { ticket++ })

const IN_FLIGHT = new Set(['starting', 'running', 'waiting'])
// The main conversation itself is not a run to read about here. Runs in flight always show.
const runs = computed(() => {
  const mine = org.runsOf(props.agentId).filter((run) => run.session_id !== props.mainSessionId)
  const live = mine.filter((run) => IN_FLIGHT.has(run.outcome))
  const rest = mine.filter((run) => !IN_FLIGHT.has(run.outcome)).slice(0, Math.max(0, SHOWN - live.length))
  return [...live, ...rest]
})
const agent = computed(() => org.byId(props.agentId))
</script>

<template>
  <section data-test="main-runs" aria-labelledby="main-runs-title" class="flex min-w-0 flex-col gap-1">
    <div class="flex items-baseline gap-3">
      <h2 id="main-runs-title" class="m-0 grow text-sm font-medium text-fg">Execuções do agente</h2>
      <RouterLink
        v-if="agent"
        data-test="main-runs-all"
        :to="{ name: 'agents', params: { projectId: agent.project_id }, query: { agente: String(agent.id), aba: 'execucoes' } }"
        class="text-xs text-info-soft hover:underline focus-visible:outline-2 focus-visible:outline-primary"
      >Ver todas</RouterLink>
    </div>
    <p v-if="error" role="alert" class="m-0 text-xs text-diff-del-fg">Não foi possível carregar as execuções. {{ error }} <button type="button" class="underline focus-visible:outline-2 focus-visible:outline-primary" @click="load">Tentar de novo</button></p>
    <p v-if="loading && !runs.length" role="status" class="m-0 text-xs text-fg-subtle">Carregando execuções…</p>
    <p v-else-if="!runs.length && !error" class="m-0 text-xs text-fg-subtle">As execuções aparecem aqui quando o agente rodar. Você pode continuar conversando abaixo.</p>
    <ul v-if="runs.length" class="m-0 flex list-none flex-col p-0">
      <AgentRunRow v-for="run in runs" :key="run.id" :run="run" />
    </ul>
  </section>
</template>
