<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import TaskRow from './TaskRow.vue'
import FilterChip from '../../ui/FilterChip.vue'
import GroupHeader from '../../ui/GroupHeader.vue'
import { TASK_STATUS_LABELS } from '../../../org'
import { errorMessage } from '../../../api/http'
import { useOrgStore } from '../../../stores/org'
import { useProjectsStore } from '../../../stores/projects'
import { useTasksStore } from '../../../stores/tasks'
import { BTN_SMALL, ERROR } from '../styles'
import type { Task, TaskFilter, TaskStatus } from '../../../types/org'

// The tasks of one project (`projectId`) or of all of them, with the filters on top. With `syncQuery` the filters
// live in the address (`?projeto=&status=a,b&responsavel=`), so the list can be linked; otherwise they are local.
const props = defineProps<{ projectId?: number; syncQuery?: boolean }>()
const emit = defineEmits<{ 'new-task': [projectId: number] }>()

const STATUSES = Object.keys(TASK_STATUS_LABELS) as TaskStatus[]
/** What "open" means: the default of the status chips. */
const OPEN: TaskStatus[] = ['todo', 'in_progress', 'in_review', 'blocked']
/** The server answers 100 tasks unless asked for more. */
const PAGE = 100
/** The counters read the open tasks once, up to this many. */
const COUNT_LIMIT = 500
const CLOSED: TaskStatus[] = ['done', 'cancelled']

const route = useRoute()
const router = useRouter()
const tasks = useTasksStore()
const org = useOrgStore()
const projects = useProjectsStore()

interface Filters { project: number | null; assignee: number | null; statuses: TaskStatus[] }

const local = reactive<Filters>({ project: null, assignee: null, statuses: [...OPEN] })

function toId(value: unknown): number | null {
  const n = typeof value === 'string' ? Number(value) : NaN
  return Number.isInteger(n) && n > 0 ? n : null
}

function fromQuery(): Filters {
  const raw = route.query.status
  const text = typeof raw === 'string' ? raw : null
  const statuses = text === null ? [...OPEN] : text === 'todas' ? [] : STATUSES.filter((s) => text.split(',').includes(s))
  return { project: toId(route.query.projeto), assignee: toId(route.query.responsavel), statuses }
}

const filters = computed<Filters>(() => (props.syncQuery ? fromQuery() : local))

function apply(next: Filters): void {
  if (!props.syncQuery) {
    Object.assign(local, next)
    return
  }
  const open = next.statuses.length === OPEN.length && OPEN.every((s) => next.statuses.includes(s))
  void router.replace({
    query: {
      ...route.query,
      projeto: next.project === null ? undefined : String(next.project),
      responsavel: next.assignee === null ? undefined : String(next.assignee),
      status: open ? undefined : next.statuses.length ? next.statuses.join(',') : 'todas',
    },
  })
}

// The responsible chosen for one project means nothing in another.
watch(() => props.projectId, () => { if (!props.syncQuery) local.assignee = null })

const effectiveProject = computed(() => props.projectId ?? filters.value.project)

function toggleStatus(status: TaskStatus): void {
  const now = filters.value.statuses
  const statuses = STATUSES.filter((s) => (s === status ? !now.includes(s) : now.includes(s)))
  apply({ ...filters.value, statuses })
}

function pickAssignee(event: Event): void {
  const id = toId((event.target as HTMLSelectElement).value)
  apply({ ...filters.value, assignee: id })
}

function pickProject(event: Event): void {
  // The responsible of another project means nothing in this one.
  apply({ ...filters.value, project: toId((event.target as HTMLSelectElement).value), assignee: null })
}

const agents = computed(() => (effectiveProject.value === null ? [...org.agents].sort((a, b) => a.name.localeCompare(b.name, 'pt-BR')) : org.byProject(effectiveProject.value)))
const agentLabel = (name: string, project: number) => (effectiveProject.value === null ? `${name} · ${projects.byId(project)?.name ?? ''}` : name)

const filter = computed<TaskFilter>(() => ({
  ...(effectiveProject.value !== null ? { project_id: effectiveProject.value } : {}),
  ...(filters.value.statuses.length ? { status: filters.value.statuses } : {}),
  ...(filters.value.assignee !== null ? { assignee_agent_id: filters.value.assignee } : {}),
}))

// Counters of the four open states, with the project and responsible filters but not the state ones.
const countFilter = computed<TaskFilter>(() => ({
  ...(effectiveProject.value !== null ? { project_id: effectiveProject.value } : {}),
  status: [...OPEN],
  ...(filters.value.assignee !== null ? { assignee_agent_id: filters.value.assignee } : {}),
  limit: COUNT_LIMIT,
}))

// Leaving the page changes the address before the list is gone: that is not a new filter.
const home = route.name

const items = ref<Task[]>([])
const loaded = ref(false)
const error = ref<string | null>(null)
let ticket = 0

async function load(): Promise<void> {
  if (props.syncQuery && route.name !== home) return
  const mine = ++ticket
  try {
    const result = await tasks.list(filter.value)
    if (mine !== ticket) return
    items.value = result
    error.value = null
    loaded.value = true
  } catch (e) {
    if (mine !== ticket) return
    error.value = errorMessage(e)
  }
}

const counts = ref<Record<string, number> | null>(null)
const countsTruncated = ref(false)
let countTicket = 0

async function loadCounts(): Promise<void> {
  if (props.syncQuery && route.name !== home) return
  const mine = ++countTicket
  try {
    const open = await tasks.list(countFilter.value)
    if (mine !== countTicket) return
    const next: Record<string, number> = {}
    for (const status of OPEN) next[status] = open.filter((t) => t.status === status).length
    counts.value = next
    countsTruncated.value = open.length >= COUNT_LIMIT
  } catch {
    // The list shows the failure; the counters just stay without numbers.
    if (mine === countTicket) counts.value = null
  }
}

// The counters are asked before the list, so the list is always the last request of a change.
watch(() => [JSON.stringify(countFilter.value), tasks.version], () => { void loadCounts() }, { immediate: true })

// The filter or an event of the board (`tasks.version`) asks for a new reading.
watch(() => [JSON.stringify(filter.value), tasks.version], () => { void load() }, { immediate: true })
onBeforeUnmount(() => { ticket++; countTicket++ })

const isDefaultFilter = computed(() => {
  const f = filters.value
  return props.projectId === undefined && f.project === null && f.assignee === null && f.statuses.length === OPEN.length && OPEN.every((s) => f.statuses.includes(s))
})

interface Place { id: number; name: string; color: string; agents: string; topId: number }

/** The projects with an organization, each with its agents (the top first), for "Onde criar". */
const places = computed<Place[]>(() => projects.regular.flatMap((project) => {
  const top = org.topOf(project.id)
  if (!top) return []
  const names = [top, ...org.byProject(project.id).filter((a) => a.id !== top.id)].map((a) => a.name)
  return [{ id: project.id, name: project.name, color: project.color, agents: joinNames(names), topId: top.id }]
}))
const withoutOrganization = computed(() => projects.regular.length - places.value.length)

function joinNames(names: string[]): string {
  return names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} e ${names.at(-1)}`
}

const talkError = ref<string | null>(null)
async function talk(place: Place): Promise<void> {
  talkError.value = null
  try {
    await org.openMain(place.topId, router)
  } catch (e) {
    talkError.value = errorMessage(e)
  }
}

const CHIP_SELECT = 'h-[30px] w-full min-w-0 cursor-pointer appearance-none rounded-full border bg-transparent pr-7 pl-[11px] text-[0.78125rem] hover:bg-card hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary'
const selectTone = (on: boolean) => (on ? 'border-fg-muted bg-card text-fg' : 'border-line text-fg-muted')

const projectName = (task: Task) => (props.projectId === undefined ? projects.byId(task.project_id)?.name ?? null : null)
</script>

<template>
  <div class="flex min-w-0 flex-col gap-4">
    <div role="group" aria-label="Filtrar por estado" class="grid grid-cols-4 border-t border-line">
      <button
        v-for="(status, index) in OPEN"
        :key="status"
        type="button"
        :data-test="`status-chip-${status}`"
        :aria-pressed="filters.statuses.includes(status)"
        class="group flex min-w-0 cursor-pointer flex-col items-start gap-0.5 border-0 border-b-2 bg-transparent px-2.5 py-3 text-left focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary sm:px-5"
        :class="[index > 0 ? 'border-l border-l-line' : '', filters.statuses.includes(status) ? 'border-b-primary' : 'border-b-line']"
        @click="toggleStatus(status)"
      >
        <span
          data-test="status-count"
          class="text-3xl leading-tight font-semibold tracking-tight tabular-nums"
          :class="!counts || counts[status] === 0 ? 'text-fg-subtle' : filters.statuses.includes(status) ? 'text-fg' : 'text-fg-muted'"
        >{{ counts ? counts[status] : '' }}</span>
        <span
          class="text-[0.78125rem] group-hover:text-fg"
          :class="filters.statuses.includes(status) ? 'text-fg-muted' : 'text-fg-subtle'"
        >{{ TASK_STATUS_LABELS[status] }}</span>
      </button>
    </div>
    <p v-if="countsTruncated" data-test="tasks-counts-truncated" class="m-0 -mt-2 text-xs text-fg-subtle">Contagem das primeiras {{ COUNT_LIMIT }} tarefas abertas.</p>

    <div class="flex flex-wrap items-center gap-2">
      <FilterChip
        v-for="status in CLOSED"
        :key="status"
        :data-test="`status-chip-${status}`"
        :label="TASK_STATUS_LABELS[status]"
        :pressed="filters.statuses.includes(status)"
        @toggle="toggleStatus(status)"
      />
      <span class="flex-1" />
      <span v-if="projectId === undefined" class="relative inline-flex max-w-52 min-w-36 items-center">
        <select data-test="project-filter" aria-label="Projeto" :class="[CHIP_SELECT, selectTone(filters.project !== null)]" :value="filters.project ?? ''" @change="pickProject">
          <option value="">Todos os projetos</option>
          <option v-for="p in projects.regular" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
        <svg class="pointer-events-none absolute right-2.5 text-fg-muted" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
      </span>
      <span class="relative inline-flex max-w-52 min-w-36 items-center">
        <select data-test="assignee-filter" aria-label="Responsável" :class="[CHIP_SELECT, selectTone(filters.assignee !== null)]" :value="filters.assignee ?? ''" @change="pickAssignee">
          <option value="">Qualquer responsável</option>
          <option v-for="a in agents" :key="a.id" :value="a.id">{{ agentLabel(a.name, a.project_id) }}</option>
        </select>
        <svg class="pointer-events-none absolute right-2.5 text-fg-muted" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
      </span>
    </div>

    <div v-if="error" role="alert" class="flex flex-wrap items-center gap-3" :class="ERROR">
      <span>Não foi possível carregar as tarefas. {{ error }}</span>
      <button type="button" data-test="tasks-retry" :class="BTN_SMALL" @click="load">Tentar de novo</button>
    </div>
    <p v-else-if="!loaded" role="status" class="m-0 text-sm text-fg-subtle">Carregando tarefas…</p>
    <section v-else-if="items.length === 0 && isDefaultFilter" data-test="tasks-empty" class="mt-2 flex max-w-3xl flex-col gap-2.5">
      <h2 class="m-0 text-lg font-semibold tracking-tight">Nenhuma tarefa aberta</h2>
      <p class="m-0 text-sm leading-relaxed text-fg-muted">Uma tarefa é um pedido que você entrega à organização de um projeto. O agente responsável trabalha nela e cada execução deixa um relato na própria tarefa.</p>
      <div data-test="tasks-where" class="mt-3 flex flex-col">
        <GroupHeader v-if="places.length" title="Onde criar" />
        <div v-for="place in places" :key="place.id" data-test="tasks-where-project" :data-project-id="place.id" class="flex min-h-14 flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-line py-2">
          <span class="size-2.5 shrink-0 rounded-[3px]" :style="{ backgroundColor: place.color }" />
          <RouterLink
            data-test="tasks-open-organization"
            :to="{ name: 'project', params: { id: place.id }, query: { visao: 'organizacao' } }"
            class="rounded-sm text-[0.90625rem] font-semibold text-fg no-underline hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          >{{ place.name }}</RouterLink>
          <span data-test="tasks-where-agents" class="min-w-0 flex-1 truncate text-[0.8125rem] text-fg-muted">{{ place.agents }}</span>
          <button type="button" data-test="tasks-where-talk" :class="BTN_SMALL" @click="talk(place)">Conversar com o CTO</button>
          <button type="button" data-test="tasks-where-new" :class="BTN_SMALL" @click="emit('new-task', place.id)">Nova tarefa</button>
        </div>
        <p v-if="talkError" role="alert" class="m-0 pt-2" :class="ERROR">{{ talkError }}</p>
        <div v-if="withoutOrganization > 0" data-test="tasks-where-others" class="flex flex-wrap items-center gap-x-3 gap-y-1 pt-2 text-[0.8125rem] text-fg-subtle">
          <span v-if="!places.length">Nenhum projeto tem organização ainda.</span>
          <span v-else-if="withoutOrganization === 1">O outro projeto ainda não tem organização.</span>
          <span v-else>Os outros {{ withoutOrganization }} projetos ainda não têm organização.</span>
          <RouterLink to="/agentes" class="rounded-sm text-primary underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary">Criar uma organização</RouterLink>
        </div>
      </div>
    </section>
    <div v-else-if="items.length === 0" data-test="tasks-empty" class="flex flex-col items-start gap-3 py-6 text-sm text-fg-muted">
      <p class="m-0">Nenhuma tarefa nos filtros selecionados.</p>
      <p v-if="projectId !== undefined" class="m-0">Crie uma tarefa em Nova tarefa ou peça ao CTO.</p>
    </div>
    <ul v-else aria-label="Tarefas" class="m-0 flex flex-col p-0">
      <TaskRow v-for="task in items" :key="task.id" :task="task" :project-name="projectName(task)" />
    </ul>
    <p v-if="items.length >= PAGE" data-test="tasks-truncated" class="m-0 text-xs text-fg-subtle">Mostrando {{ PAGE }} tarefas. Use os filtros para ver as outras.</p>
  </div>
</template>
