<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import TaskStatus from './TaskStatus.vue'
import { PRIORITY_LABELS, TASK_STATUS_LABELS } from '../../../org'
import { useOrgStore } from '../../../stores/org'
import { useProjectsStore } from '../../../stores/projects'
import { BTN, BTN_SMALL, FIELD } from '../styles'
import type { Task, TaskDetail, TaskPriority, TaskStatus as Status, TaskUpdate } from '../../../types/org'

// The top of a task: title (edited on click), status, people, priority, where it lives (branch, worktree) and how it
// connects to other tasks. Every change goes up as `change`; the screen decides how to save it.
const props = defineProps<{
  detail: TaskDetail
  parent: Task | null
  subtasks: Task[]
  busy: boolean
  /** Bumped when a change fails, so the selects go back to what the task really has. */
  resetKey: number
}>()
const emit = defineEmits<{ change: [patch: Omit<TaskUpdate, 'expected_revision'>]; unblock: []; cancel: [] }>()

const org = useOrgStore()
const projects = useProjectsStore()

const task = computed(() => props.detail.task)
const project = computed(() => projects.byId(task.value.project_id))
const STATUSES = Object.keys(TASK_STATUS_LABELS) as Status[]
const PRIORITIES = Object.keys(PRIORITY_LABELS) as TaskPriority[]
const agents = computed(() => {
  const list = org.byProject(task.value.project_id)
  // An agent that left the project still shows as the current choice instead of silently becoming "none".
  const extra = [task.value.assignee_agent_id, task.value.reviewer_agent_id]
    .filter((id): id is number => id !== null && !list.some((a) => a.id === id))
    .map((id) => org.byId(id))
    .filter((a) => a !== undefined)
  return [...list, ...extra]
})
const assignee = computed(() => (task.value.assignee_agent_id === null ? undefined : org.byId(task.value.assignee_agent_id)))
const reviewer = computed(() => (task.value.reviewer_agent_id === null ? undefined : org.byId(task.value.reviewer_agent_id)))
const agentLink = (agent: { id: number; project_id: number }) => `/agentes/${agent.project_id}?agente=${agent.id}`
const closed = computed(() => task.value.status === 'done' || task.value.status === 'cancelled')

// Only a failure rebuilds a select (a success just moves its value, so the keyboard focus stays).
const key = (name: string) => `${name}-${props.resetKey}`
const idOrNull = (event: Event): number | null => {
  const value = (event.target as HTMLSelectElement).value
  return value === '' ? null : Number(value)
}

// Title ---------------------------------------------------------------------
const editing = ref(false)
const draft = ref('')
const input = ref<HTMLInputElement | null>(null)
const editButton = ref<HTMLButtonElement | null>(null)

async function startEdit(): Promise<void> {
  draft.value = task.value.title
  editing.value = true
  await nextTick()
  input.value?.focus()
  input.value?.select()
}

// Another change is being saved: the title waits in the open input instead of being dropped.
const waiting = ref(false)
watch(() => props.busy, (busy) => { if (!busy) waiting.value = false })

async function finishEdit(save: boolean): Promise<void> {
  if (!editing.value) return
  const title = draft.value.trim()
  if (save && props.busy && title && title !== task.value.title) {
    waiting.value = true
    return
  }
  waiting.value = false
  editing.value = false
  if (save && title && title !== task.value.title) emit('change', { title })
  await nextTick()
  editButton.value?.focus()
}

// Cancelling the task asks first.
const confirming = ref(false)
</script>

<template>
  <section aria-labelledby="task-title" class="flex min-w-0 flex-col gap-4">
    <div class="flex min-w-0 flex-wrap items-start gap-x-3 gap-y-2">
      <h1 id="task-title" class="m-0 flex min-w-0 grow items-baseline gap-2 text-2xl font-semibold tracking-tight">
        <span class="shrink-0 font-mono text-base font-normal text-fg-subtle">#{{ task.id }}</span>
        <input
          v-if="editing"
          ref="input"
          v-model="draft"
          data-test="task-title-input"
          type="text"
          maxlength="160"
          aria-label="Título da tarefa"
          class="min-w-0 grow rounded-lg border border-line-strong bg-surface px-2 py-0.5 text-2xl font-semibold tracking-tight text-fg focus-visible:outline-2 focus-visible:outline-primary"
          @keydown.enter.prevent="finishEdit(true)"
          @keydown.esc.prevent="finishEdit(false)"
          @blur="finishEdit(true)"
        />
        <button
          v-else
          ref="editButton"
          type="button"
          data-test="task-title-edit"
          title="Clique para editar o título"
          class="min-w-0 cursor-text rounded border-0 bg-transparent p-0 text-left font-[inherit] text-[length:inherit] tracking-[inherit] text-fg [overflow-wrap:anywhere] hover:bg-card focus-visible:outline-2 focus-visible:outline-primary"
          :class="task.status === 'cancelled' ? 'line-through text-fg-subtle' : ''"
          @click="startEdit"
        >{{ task.title }}</button>
      </h1>
      <TaskStatus :status="task.status" class="mt-2" />
    </div>
    <p v-if="editing && waiting" data-test="task-title-wait" role="status" class="m-0 -mt-2 text-xs text-fg-muted">Aguarde a outra alteração terminar e salve o título de novo.</p>

    <div v-if="task.status === 'blocked'" data-test="task-blocked" class="flex flex-wrap items-center gap-3 rounded-lg border border-diff-del-fg/50 bg-panel p-3">
      <p data-test="task-blocked-reason" class="m-0 min-w-0 grow text-sm text-fg">
        <span class="font-semibold text-diff-del-fg">Bloqueada.</span>
        {{ task.blocked_reason || 'Sem motivo registrado.' }}
      </p>
      <button type="button" data-test="task-unblock" :class="BTN" :disabled="busy" @click="emit('unblock')">Destravar</button>
    </div>

    <dl class="m-0 grid grid-cols-[repeat(auto-fill,minmax(190px,1fr))] gap-x-4 gap-y-3 text-sm">
      <div class="flex min-w-0 flex-col gap-1">
        <dt class="text-xs text-fg-subtle"><label for="task-status-select">Estado</label></dt>
        <dd class="m-0">
          <select id="task-status-select" :key="key('status')" data-test="task-status-select" :class="FIELD" class="w-full" :value="task.status" :disabled="busy" @change="emit('change', { status: ($event.target as HTMLSelectElement).value as Status })">
            <option v-for="s in STATUSES" :key="s" :value="s">{{ TASK_STATUS_LABELS[s] }}</option>
          </select>
        </dd>
      </div>
      <div class="flex min-w-0 flex-col gap-1">
        <dt class="flex items-baseline justify-between gap-2 text-xs text-fg-subtle">
          <label for="task-assignee">Responsável</label>
          <RouterLink v-if="assignee" data-test="task-assignee-link" :to="agentLink(assignee)" class="rounded text-info-soft hover:underline focus-visible:outline-2 focus-visible:outline-primary">Abrir agente</RouterLink>
        </dt>
        <dd class="m-0">
          <select id="task-assignee" :key="key('assignee')" data-test="task-assignee" :class="FIELD" class="w-full" :value="task.assignee_agent_id ?? ''" :disabled="busy" @change="emit('change', { assignee_agent_id: idOrNull($event) })">
            <option value="">Sem responsável</option>
            <option v-for="a in agents" :key="a.id" :value="a.id">{{ a.name }}</option>
          </select>
        </dd>
      </div>
      <div class="flex min-w-0 flex-col gap-1">
        <dt class="flex items-baseline justify-between gap-2 text-xs text-fg-subtle">
          <label for="task-reviewer">Revisor</label>
          <RouterLink v-if="reviewer" data-test="task-reviewer-link" :to="agentLink(reviewer)" class="rounded text-info-soft hover:underline focus-visible:outline-2 focus-visible:outline-primary">Abrir agente</RouterLink>
        </dt>
        <dd class="m-0">
          <select id="task-reviewer" :key="key('reviewer')" data-test="task-reviewer" :class="FIELD" class="w-full" :value="task.reviewer_agent_id ?? ''" :disabled="busy" @change="emit('change', { reviewer_agent_id: idOrNull($event) })">
            <option value="">Sem revisor</option>
            <option v-for="a in agents" :key="a.id" :value="a.id">{{ a.name }}</option>
          </select>
        </dd>
      </div>
      <div class="flex min-w-0 flex-col gap-1">
        <dt class="text-xs text-fg-subtle"><label for="task-priority">Prioridade</label></dt>
        <dd class="m-0">
          <select id="task-priority" :key="key('priority')" data-test="task-priority" :class="FIELD" class="w-full" :value="task.priority" :disabled="busy" @change="emit('change', { priority: ($event.target as HTMLSelectElement).value as TaskPriority })">
            <option v-for="p in PRIORITIES" :key="p" :value="p">{{ PRIORITY_LABELS[p] }}</option>
          </select>
        </dd>
      </div>
      <div class="flex min-w-0 flex-col gap-1">
        <dt class="text-xs text-fg-subtle">Projeto</dt>
        <dd class="m-0 min-w-0 truncate">
          <RouterLink data-test="task-project" :to="`/agentes/${task.project_id}`" class="rounded text-info-soft hover:underline focus-visible:outline-2 focus-visible:outline-primary">{{ project?.name ?? `Projeto ${task.project_id}` }}</RouterLink>
        </dd>
      </div>
      <div class="flex min-w-0 flex-col gap-1">
        <dt class="text-xs text-fg-subtle">Execuções</dt>
        <dd data-test="task-run-count" class="m-0 font-mono text-xs text-fg-muted">{{ task.run_count }} de {{ task.max_runs }}</dd>
      </div>
      <div v-if="task.branch" class="flex min-w-0 flex-col gap-1">
        <dt class="text-xs text-fg-subtle">Branch</dt>
        <dd data-test="task-branch" class="m-0 font-mono text-xs text-fg-muted [overflow-wrap:anywhere]">{{ task.branch }}</dd>
      </div>
      <div v-if="task.worktree_path" class="flex min-w-0 flex-col gap-1">
        <dt class="text-xs text-fg-subtle">Worktree</dt>
        <dd data-test="task-worktree" class="m-0 font-mono text-xs text-fg-muted [overflow-wrap:anywhere]">{{ task.worktree_path }}</dd>
      </div>
      <div v-if="task.parent_task_id !== null" class="flex min-w-0 flex-col gap-1">
        <dt class="text-xs text-fg-subtle">Tarefa pai</dt>
        <dd class="m-0 min-w-0">
          <RouterLink data-test="task-parent" :to="`/tarefas/${task.parent_task_id}`" class="rounded text-info-soft [overflow-wrap:anywhere] hover:underline focus-visible:outline-2 focus-visible:outline-primary">#{{ task.parent_task_id }}<template v-if="parent"> {{ parent.title }}</template></RouterLink>
        </dd>
      </div>
    </dl>

    <section v-if="subtasks.length" aria-labelledby="task-subtasks-title" class="flex flex-col gap-1">
      <h2 id="task-subtasks-title" class="m-0 text-sm font-semibold">Subtarefas</h2>
      <ul aria-labelledby="task-subtasks-title" class="m-0 flex list-none flex-col p-0">
        <li v-for="sub in subtasks" :key="sub.id" class="border-b border-line">
          <RouterLink data-test="task-subtask" :to="`/tarefas/${sub.id}`" class="flex min-w-0 items-center gap-3 rounded px-1 py-1.5 text-sm text-fg no-underline hover:bg-card focus-visible:outline-2 focus-visible:outline-primary">
            <span class="shrink-0 font-mono text-xs text-fg-subtle">#{{ sub.id }}</span>
            <span class="min-w-0 grow [overflow-wrap:anywhere]">{{ sub.title }}</span>
            <TaskStatus :status="sub.status" />
          </RouterLink>
        </li>
      </ul>
    </section>

    <div v-if="!closed" class="flex flex-wrap items-center gap-2">
      <button v-if="!confirming" type="button" data-test="task-cancel" :class="BTN_SMALL" :disabled="busy" @click="confirming = true">Cancelar tarefa</button>
      <template v-else>
        <span class="text-sm text-fg-muted">Cancelar esta tarefa?</span>
        <button type="button" data-test="task-cancel-confirm" :class="BTN" :disabled="busy" @click="confirming = false; emit('cancel')">Cancelar a tarefa</button>
        <button type="button" data-test="task-cancel-back" :class="BTN_SMALL" @click="confirming = false">Voltar</button>
      </template>
    </div>
  </section>
</template>
