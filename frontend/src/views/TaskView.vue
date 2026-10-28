<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import TaskComposer from '../components/org/tasks/TaskComposer.vue'
import TaskHeader from '../components/org/tasks/TaskHeader.vue'
import TaskMarkdown from '../components/org/tasks/TaskMarkdown.vue'
import TaskRuns from '../components/org/tasks/TaskRuns.vue'
import TaskSidebar from '../components/org/tasks/TaskSidebar.vue'
import TaskThread from '../components/org/tasks/TaskThread.vue'
import TasksPage from '../components/org/tasks/TasksPage.vue'
import { errorMessage } from '../api/http'
import { BTN, ERROR } from '../components/org/styles'
import { TaskConflictError, useTasksStore } from '../stores/tasks'
import type { Task, TaskUpdate } from '../types/org'

const props = defineProps<{ id: string }>()
const tasks = useTasksStore()

const taskId = computed(() => Number(props.id))
const detail = computed(() => tasks.details[taskId.value])

const loading = ref(true)
const loadError = ref<string | null>(null)
let loadTicket = 0

async function load(): Promise<void> {
  const mine = ++loadTicket
  loading.value = true
  loadError.value = null
  try {
    await tasks.refresh(taskId.value)
  } catch (e) {
    if (mine === loadTicket) loadError.value = errorMessage(e)
  } finally {
    if (mine === loadTicket) loading.value = false
  }
}

// Subtasks and the parent come from the tasks of the same project.
const related = ref<Task[]>([])
let relatedTicket = 0
async function loadRelated(projectId: number): Promise<void> {
  const mine = ++relatedTicket
  try {
    const list = await tasks.list({ project_id: projectId, limit: 500 })
    if (mine === relatedTicket) related.value = list
  } catch {
    // They only complement the screen; without them the task still opens.
  }
}
const projectId = computed(() => detail.value?.task.project_id)
watch(() => [projectId.value, tasks.version], () => {
  if (projectId.value !== undefined) void loadRelated(projectId.value)
}, { immediate: true })
const subtasks = computed(() => related.value.filter((t) => t.parent_task_id === taskId.value))
const parent = computed(() => {
  const parentId = detail.value?.task.parent_task_id
  return parentId == null ? null : related.value.find((t) => t.id === parentId) ?? null
})

watch(taskId, () => { related.value = []; void load() }, { immediate: true })
onBeforeUnmount(() => { loadTicket++; relatedTicket++ })

// Changes --------------------------------------------------------------------
const busy = ref(false)
const actionError = ref<string | null>(null)
const resetKey = ref(0)

/** Saves a change against the revision this screen read; a refusal reloads the task and applies nothing again. */
async function run(action: (revision: number) => Promise<unknown>): Promise<void> {
  const current = detail.value
  if (!current || busy.value) return
  busy.value = true
  actionError.value = null
  try {
    await action(current.task.revision)
  } catch (e) {
    resetKey.value++
    actionError.value = e instanceof TaskConflictError && e.stale ? 'A tarefa mudou. Veja a versão atual.' : errorMessage(e)
  } finally {
    busy.value = false
  }
}

const change = (patch: Omit<TaskUpdate, 'expected_revision'>) => run((revision) => tasks.update(taskId.value, { expected_revision: revision, ...patch }))
const unblock = () => run((revision) => tasks.unblock(taskId.value, revision))
const cancel = () => change({ status: 'cancelled' })
</script>

<template>
  <TasksPage title="Tarefa">
    <template #heading><RouterLink data-test="task-back" to="/tarefas" class="rounded text-sm text-info-soft no-underline hover:underline focus-visible:outline-2 focus-visible:outline-primary">← Tarefas</RouterLink><span class="grow" /></template>

    <div v-if="loadError && !detail" role="alert" :class="ERROR" class="flex flex-wrap items-center gap-3">
      <span>{{ loadError }}</span>
      <button type="button" data-test="task-retry" :class="BTN" @click="load">Tentar de novo</button>
    </div>
    <p v-else-if="!detail" role="status" class="m-0 text-fg-subtle">Carregando tarefa…</p>

    <template v-else>
      <p v-if="actionError" role="alert" data-test="task-error" :class="ERROR">{{ actionError }}</p>
      <div class="grid min-w-0 gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div class="flex min-w-0 flex-col gap-6">
          <TaskHeader :detail="detail" :parent="parent" :subtasks="subtasks" :busy="busy" :reset-key="resetKey" @change="change" @unblock="unblock" @cancel="cancel" />
          <section v-if="detail.task.description" aria-label="Descrição" data-test="task-description">
            <TaskMarkdown :text="detail.task.description" />
          </section>
          <section aria-labelledby="task-thread-title" class="flex flex-col gap-3">
            <h2 id="task-thread-title" class="m-0 text-sm font-semibold">Conversa</h2>
            <TaskThread :comments="detail.comments" />
            <TaskComposer :task-id="detail.task.id" />
          </section>
          <TaskRuns :runs="detail.runs" />
        </div>
        <aside aria-label="Decisões, pull requests e verificações" class="min-w-0 max-lg:order-first">
          <TaskSidebar :detail="detail" />
        </aside>
      </div>
    </template>
  </TasksPage>
</template>
