<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { errorMessage } from '../../../api/http'
import { useOrgStore } from '../../../stores/org'
import type { Run, RunOutcome } from '../../../types/org'
import AgentRunRow from '../agent/AgentRunRow.vue'
import { ERROR, FIELD } from '../styles'

// The runs of all the agents of the project, newest first, each with the name of its agent.
const props = defineProps<{ projectId: number }>()
const org = useOrgStore()

/** What the "Problemas" filter keeps: the same set as the runs list of the agent panel. */
const PROBLEMS: ReadonlySet<RunOutcome> = new Set(['failed', 'waiting', 'missed', 'skipped'])

const agents = computed(() => org.byProject(props.projectId))
const agentFilter = ref('')
const onlyProblems = ref(false)
const loaded = ref(false)
/** Agent id -> why its runs could not be read. */
const failures = ref<Record<number, string>>({})

const everyRun = computed<Run[]>(() =>
  agents.value
    .flatMap((agent) => org.runsOf(agent.id))
    .sort((a, b) => b.started_at - a.started_at || b.id - a.id),
)
const visible = computed(() =>
  everyRun.value.filter(
    (run) => (agentFilter.value === '' || run.agent_id === Number(agentFilter.value)) && (!onlyProblems.value || PROBLEMS.has(run.outcome)),
  ),
)
const errors = computed(() =>
  agents.value.filter((a) => failures.value[a.id]).map((a) => `${a.name}: ${failures.value[a.id]}`),
)

function nameOf(agentId: number): string | null {
  return org.byId(agentId)?.name ?? null
}

const loadedIds = new Set<number>()
async function load(): Promise<void> {
  const wanted = agents.value.filter((a) => !loadedIds.has(a.id))
  wanted.forEach((a) => loadedIds.add(a.id))
  await Promise.all(wanted.map(async (agent) => {
    try {
      await org.loadRuns(agent.id)
      const { [agent.id]: _, ...rest } = failures.value
      failures.value = rest
    } catch (e) {
      loadedIds.delete(agent.id)
      failures.value = { ...failures.value, [agent.id]: errorMessage(e) }
    }
  }))
  loaded.value = true
}

onMounted(() => { void load() })
// An agent created (or loaded) after the tab opened gets its runs too.
watch(() => agents.value.map((a) => a.id).join(','), () => { void load() })
watch(() => props.projectId, () => {
  loadedIds.clear()
  failures.value = {}
  agentFilter.value = ''
  loaded.value = false
  void load()
})
// The agent picked in the filter may leave the project (deleted): go back to all.
watch(agents, (list) => {
  if (agentFilter.value !== '' && !list.some((a) => String(a.id) === agentFilter.value)) agentFilter.value = ''
})
</script>

<template>
  <div data-test="runs-tab" :data-project-id="projectId" class="flex min-w-0 flex-col gap-4 py-4">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <h2 id="runs-heading" class="m-0 text-base font-semibold text-fg">Execuções</h2>
      <div class="flex flex-wrap items-center gap-2">
        <label class="sr-only" for="runs-agent-filter">Filtrar por agente</label>
        <select id="runs-agent-filter" v-model="agentFilter" data-test="runs-agent-filter" :class="[FIELD, 'max-w-48']">
          <option value="">Todos os agentes</option>
          <option v-for="agent in agents" :key="agent.id" :value="String(agent.id)">{{ agent.name }}</option>
        </select>
        <button
          type="button"
          data-test="runs-filter-problems"
          :aria-pressed="onlyProblems"
          class="h-9 rounded-lg border px-3.5 text-sm font-medium focus-visible:outline-2 focus-visible:outline-primary"
          :class="onlyProblems ? 'border-line-strong bg-elevated text-fg' : 'border-line bg-transparent text-fg-muted hover:bg-card'"
          @click="onlyProblems = !onlyProblems"
        >Problemas</button>
      </div>
    </div>

    <p v-for="message in errors" :key="message" data-test="runs-error" role="alert" :class="ERROR">Não foi possível carregar as execuções de {{ message }}</p>

    <p v-if="agents.length === 0" data-test="runs-empty" class="m-0 text-sm text-fg-muted">Este projeto ainda não tem agentes, então não há execuções.</p>
    <p v-else-if="!loaded && everyRun.length === 0" role="status" class="m-0 text-sm text-fg-subtle">Carregando execuções…</p>
    <p v-else-if="visible.length === 0" data-test="runs-empty" class="m-0 text-sm text-fg-muted">
      {{ everyRun.length === 0 ? 'Ainda não rodou.' : onlyProblems ? 'Nenhum problema nas execuções.' : 'Este agente ainda não rodou.' }}
    </p>
    <ul v-else aria-labelledby="runs-heading" class="m-0 list-none p-0">
      <AgentRunRow v-for="run in visible" :key="run.id" :run="run" :agent-name="nameOf(run.agent_id)" />
    </ul>
  </div>
</template>
