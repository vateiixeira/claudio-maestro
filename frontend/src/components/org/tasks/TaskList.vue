<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import TaskRow from './TaskRow.vue'
import { TASK_STATUS_LABELS } from '../../../org'
import { errorMessage } from '../../../api/http'
import { useOrgStore } from '../../../stores/org'
import { useProjectsStore } from '../../../stores/projects'
import { useTasksStore } from '../../../stores/tasks'
import { BTN_SMALL, ERROR, FIELD } from '../styles'
import type { Task, TaskFilter, TaskStatus } from '../../../types/org'

// The tasks of one project (`projectId`) or of all of them, with the filters on top. With `syncQuery` the filters
// live in the address (`?projeto=&status=a,b&responsavel=`), so the list can be linked; otherwise they are local.
const props = defineProps<{ projectId?: number; syncQuery?: boolean }>()

const STATUSES = Object.keys(TASK_STATUS_LABELS) as TaskStatus[]
/** What "open" means: the default of the status chips. */
const OPEN: TaskStatus[] = ['todo', 'in_progress', 'in_review', 'blocked']
/** The server answers 100 tasks unless asked for more. */
const PAGE = 100

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

// The filter or an event of the board (`tasks.version`) asks for a new reading.
watch(() => [JSON.stringify(filter.value), tasks.version], () => { void load() }, { immediate: true })
onBeforeUnmount(() => { ticket++ })

const projectName = (task: Task) => (props.projectId === undefined ? projects.byId(task.project_id)?.name ?? null : null)
</script>

<template>
  <div class="flex min-w-0 flex-col gap-3">
    <div class="flex flex-wrap items-center gap-x-4 gap-y-2">
      <div role="group" aria-label="Filtrar por estado" class="flex flex-wrap gap-1.5">
        <button
          v-for="status in STATUSES"
          :key="status"
          type="button"
          :data-test="`status-chip-${status}`"
          :aria-pressed="filters.statuses.includes(status)"
          class="h-7 cursor-pointer rounded-full border px-3 text-xs font-medium focus-visible:outline-2 focus-visible:outline-primary"
          :class="filters.statuses.includes(status) ? 'border-fg-muted bg-card text-fg' : 'border-line-strong bg-transparent text-fg-muted hover:bg-card hover:text-fg'"
          @click="toggleStatus(status)"
        >{{ TASK_STATUS_LABELS[status] }}</button>
      </div>
      <label v-if="projectId === undefined" class="flex items-center gap-2 text-xs text-fg-subtle">
        Projeto
        <select data-test="project-filter" :class="FIELD" class="max-w-48" :value="filters.project ?? ''" @change="pickProject">
          <option value="">Todos os projetos</option>
          <option v-for="p in projects.projects" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
      </label>
      <label class="flex items-center gap-2 text-xs text-fg-subtle">
        Responsável
        <select data-test="assignee-filter" :class="FIELD" class="max-w-48" :value="filters.assignee ?? ''" @change="pickAssignee">
          <option value="">Todos</option>
          <option v-for="a in agents" :key="a.id" :value="a.id">{{ agentLabel(a.name, a.project_id) }}</option>
        </select>
      </label>
    </div>

    <div v-if="error" role="alert" class="flex flex-wrap items-center gap-3" :class="ERROR">
      <span>Não foi possível carregar as tarefas. {{ error }}</span>
      <button type="button" data-test="tasks-retry" :class="BTN_SMALL" @click="load">Tentar de novo</button>
    </div>
    <p v-else-if="!loaded" role="status" class="m-0 text-sm text-fg-subtle">Carregando tarefas…</p>
    <p v-else-if="items.length === 0" data-test="tasks-empty" class="m-0 py-6 text-sm text-fg-muted">Nenhuma tarefa. Crie uma ou peça ao CTO.</p>
    <ul v-else aria-label="Tarefas" class="m-0 flex flex-col p-0">
      <TaskRow v-for="task in items" :key="task.id" :task="task" :project-name="projectName(task)" />
    </ul>
    <p v-if="items.length >= PAGE" data-test="tasks-truncated" class="m-0 text-xs text-fg-subtle">Mostrando {{ PAGE }} tarefas. Use os filtros para ver as outras.</p>
  </div>
</template>
