<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { errorMessage } from '../../../api/http'
import { useOrgStore } from '../../../stores/org'
import { useProjectsStore } from '../../../stores/projects'
import { useTasksStore } from '../../../stores/tasks'
import { BTN_PRIMARY } from '../styles'

// The quick bar at the top of Tarefas: a title, the project (only those with an organization) and the responsible
// (the top agent by default). It creates the task and stays on the list.
const props = defineProps<{ projectId: number | null }>()
const emit = defineEmits<{ 'update:projectId': [id: number] }>()

const org = useOrgStore()
const projects = useProjectsStore()
const tasks = useTasksStore()

const options = computed(() => projects.regular.filter((p) => org.byProject(p.id).length > 0).sort((a, b) => a.name.localeCompare(b.name, 'pt-BR')))

const chosen = ref<number | null>(props.projectId)
watch(() => props.projectId, (id) => { chosen.value = id })
/** What the person chose, or the first project if that one has no organization (any more). */
const project = computed(() => (options.value.some((p) => p.id === chosen.value) ? chosen.value : options.value[0]?.id ?? null))
const projectColor = computed(() => (project.value === null ? undefined : projects.byId(project.value)?.color))

const agents = computed(() => (project.value === null ? [] : org.byProject(project.value)))
// Until the person picks one, the responsible is the top of the project (it may arrive after the bar opens).
const pickedAssignee = ref<string | null>(null)
watch(project, () => { pickedAssignee.value = null })
const assignee = computed(() => pickedAssignee.value ?? String(project.value === null ? '' : org.topOf(project.value)?.id ?? ''))

const title = ref('')
const input = ref<HTMLInputElement | null>(null)
const busy = ref(false)
const error = ref<string | null>(null)
const created = ref<number | null>(null)
const canSubmit = computed(() => project.value !== null && title.value.trim().length > 0 && !busy.value)

function pickProject(event: Event): void {
  const id = Number((event.target as HTMLSelectElement).value)
  chosen.value = id
  emit('update:projectId', id)
}

function focus(): void {
  input.value?.focus()
}
defineExpose({ focus })

async function submit(): Promise<void> {
  if (!canSubmit.value || project.value === null) return
  busy.value = true
  error.value = null
  created.value = null
  try {
    const task = await tasks.create({
      project_id: project.value,
      title: title.value.trim(),
      assignee_agent_id: assignee.value ? Number(assignee.value) : null,
    })
    title.value = ''
    created.value = task.id
    await nextTick()
    focus()
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}

function onEnter(event: KeyboardEvent): void {
  // Enter that confirms an input method composition is not a request to create.
  if (event.isComposing) return
  event.preventDefault()
  void submit()
}

const CHIP = 'h-[30px] w-full min-w-0 cursor-pointer appearance-none rounded-full border border-line-strong bg-transparent pr-7 text-[0.78125rem] text-fg hover:bg-card focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary'
</script>

<template>
  <form
    v-if="options.length"
    data-test="quick-task"
    class="flex flex-col rounded-2xl border border-line-strong bg-panel focus-within:outline-2 focus-within:outline-primary"
    @submit.prevent="submit"
  >
    <input
      ref="input"
      v-model="title"
      data-test="quick-task-title"
      type="text"
      aria-label="Nova tarefa"
      placeholder="O que precisa ser feito?"
      maxlength="160"
      autocomplete="off"
      :readonly="busy"
      class="block h-[52px] w-full rounded-t-2xl border-0 bg-transparent px-[18px] text-[0.9375rem] text-fg outline-none placeholder:text-fg-subtle"
      @keydown.enter="onEnter"
    />
    <div class="flex flex-wrap items-center gap-x-2 gap-y-2 pt-1.5 pr-2.5 pb-2.5 pl-4">
      <label class="flex items-center gap-2 text-xs text-fg-muted">
        Projeto
        <span class="relative inline-flex max-w-52 items-center">
          <span class="pointer-events-none absolute left-3 size-2 rounded-[2px]" :style="{ backgroundColor: projectColor }" />
          <select data-test="quick-task-project" :class="CHIP" class="pl-7" :value="project ?? ''" @change="pickProject">
            <option v-for="p in options" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
          <svg class="pointer-events-none absolute right-2.5 text-fg-muted" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
        </span>
      </label>
      <label class="flex items-center gap-2 text-xs text-fg-muted sm:ml-2.5">
        Responsável
        <span class="relative inline-flex max-w-52 items-center">
          <select data-test="quick-task-assignee" :class="CHIP" class="pl-3" :value="assignee" @change="pickedAssignee = ($event.target as HTMLSelectElement).value">
            <option value="">Sem responsável</option>
            <option v-for="a in agents" :key="a.id" :value="String(a.id)">{{ a.name }}</option>
          </select>
          <svg class="pointer-events-none absolute right-2.5 text-fg-muted" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
        </span>
      </label>
      <span class="flex-1" />
      <span class="hidden rounded border border-line px-1.5 font-mono text-[0.71875rem] text-fg-muted sm:inline" aria-hidden="true">Enter</span>
      <button type="submit" data-test="quick-task-submit" :class="BTN_PRIMARY" :disabled="!canSubmit">{{ busy ? 'Criando…' : 'Criar tarefa' }}</button>
    </div>
    <p v-if="error" data-test="quick-task-error" role="alert" class="m-0 px-4 pb-2.5 text-sm text-diff-del-fg">{{ error }}</p>
    <p v-else-if="created !== null" data-test="quick-task-created" role="status" class="m-0 flex items-center gap-2 px-4 pb-2.5 text-sm text-fg-muted">
      <span>Tarefa #{{ created }} criada.</span>
      <RouterLink :to="`/tarefas/${created}`" class="rounded-sm text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary">Abrir</RouterLink>
    </p>
  </form>
</template>
