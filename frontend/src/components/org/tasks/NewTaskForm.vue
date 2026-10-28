<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { PRIORITY_LABELS } from '../../../org'
import { errorMessage } from '../../../api/http'
import { useOrgStore } from '../../../stores/org'
import { useTasksStore } from '../../../stores/tasks'
import { AREA, BTN, BTN_PRIMARY, ERROR, FIELD } from '../styles'
import type { Task, TaskPriority } from '../../../types/org'

// A new task of the project: it opens the task right after.
const props = defineProps<{ projectId: number }>()
const emit = defineEmits<{ created: [task: Task]; cancel: [] }>()

const org = useOrgStore()
const tasks = useTasksStore()
const router = useRouter()

const agents = computed(() => org.byProject(props.projectId))
const PRIORITIES = Object.keys(PRIORITY_LABELS) as TaskPriority[]

const title = ref('')
const description = ref('')
const priority = ref<TaskPriority>('normal')
// Until the person picks one, the responsible is the top of the project (it may arrive after the form opens).
const pickedAssignee = ref<string | null>(null)
const pickedReviewer = ref('')
const assignee = computed(() => pickedAssignee.value ?? String(org.topOf(props.projectId)?.id ?? ''))

const busy = ref(false)
const error = ref<string | null>(null)
const canSubmit = computed(() => title.value.trim().length > 0 && !busy.value)

async function submit(): Promise<void> {
  if (!canSubmit.value) return
  busy.value = true
  error.value = null
  try {
    const task = await tasks.create({
      project_id: props.projectId,
      title: title.value.trim(),
      description: description.value,
      assignee_agent_id: assignee.value ? Number(assignee.value) : null,
      reviewer_agent_id: pickedReviewer.value ? Number(pickedReviewer.value) : null,
      priority: priority.value,
    })
    emit('created', task)
    await router.push(`/tarefas/${task.id}`)
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <form aria-labelledby="new-task-heading" class="flex flex-col gap-3 rounded-lg border border-line bg-panel p-3" @submit.prevent="submit">
    <h2 id="new-task-heading" class="m-0 text-sm font-semibold">Nova tarefa</h2>
    <label class="flex flex-col gap-1 text-xs text-fg-muted">
      Título
      <input v-model="title" data-test="new-task-title" type="text" maxlength="160" required :class="FIELD" class="text-fg" autocomplete="off" />
    </label>
    <label class="flex flex-col gap-1 text-xs text-fg-muted">
      Descrição (markdown, opcional)
      <textarea v-model="description" data-test="new-task-description" rows="4" :class="AREA" />
    </label>
    <div class="flex flex-wrap gap-3">
      <label class="flex min-w-36 flex-1 flex-col gap-1 text-xs text-fg-muted">
        Responsável
        <select data-test="new-task-assignee" :class="FIELD" :value="assignee" @change="pickedAssignee = ($event.target as HTMLSelectElement).value">
          <option value="">Sem responsável</option>
          <option v-for="a in agents" :key="a.id" :value="String(a.id)">{{ a.name }}</option>
        </select>
      </label>
      <label class="flex min-w-36 flex-1 flex-col gap-1 text-xs text-fg-muted">
        Revisor (opcional)
        <select v-model="pickedReviewer" data-test="new-task-reviewer" :class="FIELD">
          <option value="">Sem revisor</option>
          <option v-for="a in agents" :key="a.id" :value="String(a.id)">{{ a.name }}</option>
        </select>
      </label>
      <label class="flex min-w-28 flex-col gap-1 text-xs text-fg-muted">
        Prioridade
        <select v-model="priority" data-test="new-task-priority" :class="FIELD">
          <option v-for="p in PRIORITIES" :key="p" :value="p">{{ PRIORITY_LABELS[p] }}</option>
        </select>
      </label>
    </div>
    <p v-if="error" role="alert" :class="ERROR">{{ error }}</p>
    <div class="flex gap-2">
      <button type="submit" data-test="new-task-submit" :class="BTN_PRIMARY" :disabled="!canSubmit">{{ busy ? 'Criando…' : 'Criar tarefa' }}</button>
      <button type="button" data-test="new-task-cancel" :class="BTN" @click="emit('cancel')">Cancelar</button>
    </div>
  </form>
</template>
