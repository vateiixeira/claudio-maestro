<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { errorMessage } from '../../../api/http'
import { useMinuteClock } from '../../../minuteClock'
import { useOrgStore } from '../../../stores/org'
import type { Run } from '../../../types/org'
import FilterChip from '../../ui/FilterChip.vue'
import { ERROR, FIELD } from '../styles'
import RunLine from './RunLine.vue'
import { PROBLEM_OUTCOMES, groupByDay, offAgentsText, runLines, runTime, runsSummary } from './runDays'

// The runs of all the agents of the project, newest first, grouped by day, each with the name of its agent.
const props = defineProps<{ projectId: number }>()
const org = useOrgStore()

const agents = computed(() => org.byProject(props.projectId))
const agentFilter = ref('')
const onlyProblems = ref(false)
const loaded = ref(false)
/** Agent id -> why its runs could not be read. */
const failures = ref<Record<number, string>>({})

const everyRun = computed<Run[]>(() =>
  agents.value
    .flatMap((agent) => org.runsOf(agent.id))
    .sort((a, b) => runTime(b) - runTime(a) || b.id - a.id),
)
/** The runs of the agent in the filter (or of all), before the "Problemas" filter. */
const ofAgent = computed(() =>
  everyRun.value.filter((run) => agentFilter.value === '' || run.agent_id === Number(agentFilter.value)),
)
const problems = computed(() => ofAgent.value.filter((run) => PROBLEM_OUTCOMES.has(run.outcome)))
const visible = computed(() => (onlyProblems.value ? problems.value : ofAgent.value))
// The app clock, so "Hoje" and "Ontem" turn over at midnight without a reload.
const clock = useMinuteClock()
const days = computed(() => groupByDay(runLines(visible.value), new Date(clock.value)))
const summary = computed(() => runsSummary(ofAgent.value))
const offText = computed(() => offAgentsText(agents.value.filter((a) => !a.enabled).map((a) => a.name)))
/** The longest duration, in seconds: the full width of the bars. */
const maxSeconds = computed(() =>
  visible.value.reduce((max, run) => (run.ended_at === null ? max : Math.max(max, run.ended_at - run.started_at)), 0),
)
const errors = computed(() =>
  agents.value.filter((a) => failures.value[a.id]).map((a) => `${a.name}: ${failures.value[a.id]}`),
)

function nameOf(agentId: number): string | null {
  return org.byId(agentId)?.name ?? null
}
function lineKey(line: ReturnType<typeof runLines>[number]): string {
  return line.kind === 'run' ? `r${line.run.id}` : `m${line.runs[0]!.id}`
}

const loadedIds = new Set<number>()
async function load(): Promise<void> {
  const wanted = agents.value.filter((a) => !loadedIds.has(a.id))
  wanted.forEach((a) => loadedIds.add(a.id))
  await Promise.all(wanted.map(async (agent) => {
    try {
      await org.ensureRuns(agent.id)
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
        <FilterChip data-test="runs-filter-problems" label="Só problemas" :count="problems.length" :pressed="onlyProblems" @toggle="onlyProblems = !onlyProblems" />
      </div>
    </div>

    <p v-for="message in errors" :key="message" data-test="runs-error" role="alert" :class="ERROR">Não foi possível carregar as execuções de {{ message }}</p>

    <div v-if="offText || summary" class="flex min-w-0 flex-col gap-1 text-[0.8125rem] text-fg-muted">
      <p v-if="offText" data-test="runs-off" class="m-0 text-secondary">{{ offText }}</p>
      <p v-if="summary" data-test="runs-summary" class="m-0">{{ summary }}</p>
    </div>

    <!-- Nothing is said about what has not been read: without the agents (or when their runs failed to load) the line stays out. -->
    <template v-if="agents.length === 0">
      <p v-if="org.loaded && !org.error" data-test="runs-empty" class="m-0 text-sm text-fg-muted">Este projeto ainda não tem agentes, então não há execuções.</p>
      <p v-else-if="!org.loaded" data-test="runs-loading" role="status" class="m-0 text-sm text-fg-muted">Carregando execuções…</p>
    </template>
    <p v-else-if="!loaded && everyRun.length === 0" data-test="runs-loading" role="status" class="m-0 text-sm text-fg-muted">Carregando execuções…</p>
    <p v-else-if="visible.length === 0 && (everyRun.length > 0 || errors.length === 0)" data-test="runs-empty" class="m-0 text-sm text-fg-muted">
      {{ everyRun.length === 0 ? 'Ainda não rodou.' : onlyProblems ? 'Nenhum problema nas execuções.' : 'Este agente ainda não rodou.' }}
    </p>
    <ul v-else-if="days.length > 0" aria-labelledby="runs-heading" class="m-0 flex list-none flex-col gap-0.5 p-0">
      <li v-for="day in days" :key="day.key" data-test="run-day" :data-day="day.key" class="min-w-0">
        <div class="mt-1 flex h-[1.875rem] items-center gap-3 text-fg-muted">
          <span data-test="run-day-label" class="font-mono text-[0.65625rem] font-semibold tracking-[0.08em] uppercase">{{ day.label }}</span>
          <span class="h-px flex-1 bg-line" aria-hidden="true"></span>
        </div>
        <ul class="m-0 flex list-none flex-col gap-0.5 p-0">
          <RunLine v-for="line in day.lines" :key="lineKey(line)" :line="line" :agent-name="nameOf" :max-seconds="maxSeconds" :all="everyRun" />
        </ul>
      </li>
    </ul>
  </div>
</template>
