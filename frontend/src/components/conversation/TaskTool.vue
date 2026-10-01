<script setup lang="ts">
import { computed } from 'vue'
import { TASK_STATUS_LABEL, createdTaskId, taskStatus, type TaskEntry, type TaskStatus } from '../../conversation/tasks'
import { str } from '../../conversation/tool'
import type { ToolItem } from '../../types/conversation'

const props = defineProps<{ item: ToolItem; tasks?: TaskEntry[] | null }>()

const MARK: Record<TaskStatus, string> = { pending: '○', in_progress: '◐', completed: '●' }

const input = computed(() => props.item.input ?? {})
const heading = computed(() => {
  if (props.item.name === 'TaskCreate') return 'Nova tarefa'
  if (props.item.name === 'TaskUpdate') return 'Tarefa atualizada'
  return 'Lista de tarefas'
})
const summary = computed(() => {
  if (props.item.name === 'TaskCreate') {
    return { subject: str(input.value.subject) || str(input.value.description), status: 'pending' as TaskStatus, id: createdTaskId(props.item.result?.content) }
  }
  if (props.item.name === 'TaskUpdate') {
    const id = String(input.value.taskId ?? '')
    const known = props.tasks?.find((t) => t.id === id)
    return { subject: str(input.value.subject) || known?.subject || `Tarefa #${id}`, status: taskStatus(input.value.status), id }
  }
  return null
})
</script>

<template>
  <div data-test="task-tool" class="flex flex-col gap-1.5 rounded-lg border border-line bg-panel px-3 py-2">
    <div class="flex items-center gap-2 text-xs">
      <span class="font-semibold text-fg-subtle">{{ heading }}</span>
      <template v-if="summary">
        <span class="min-w-0 grow truncate text-fg">{{ summary.subject }}</span>
        <span :class="summary.status === 'completed' ? 'text-primary-soft' : summary.status === 'in_progress' ? 'text-secondary-soft' : 'text-fg-subtle'">{{ TASK_STATUS_LABEL[summary.status] }}</span>
      </template>
    </div>
    <ul v-if="tasks && tasks.length" data-test="task-list" class="m-0 flex list-none flex-col gap-1 border-t border-line p-0 pt-1.5">
      <li v-for="task in tasks" :key="task.id" data-test="task-row" class="flex items-center gap-2 text-sm">
        <span aria-hidden="true" :class="task.status === 'completed' ? 'text-primary' : task.status === 'in_progress' ? 'text-secondary' : 'text-fg-subtle'">{{ MARK[task.status] }}</span>
        <span class="min-w-0 grow" :class="task.status === 'completed' ? 'text-fg-muted line-through' : 'text-fg'">{{ task.subject }}</span>
        <span class="text-xs text-fg-subtle">{{ TASK_STATUS_LABEL[task.status] }}</span>
      </li>
    </ul>
  </div>
</template>
