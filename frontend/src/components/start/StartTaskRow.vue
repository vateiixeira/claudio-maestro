<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { PRIORITY_LABELS, TASK_STATUS_LABELS, taskStatusShape } from '../../org'
import { useOrgStore } from '../../stores/org'
import { useProjectsStore } from '../../stores/projects'
import type { Task } from '../../types/org'

// One task in the lists of the start screen: its status by shape and word, the title, and where it stands
// (number, project, assignee). The whole row opens the task.
const props = defineProps<{ task: Task }>()
const org = useOrgStore()
const projects = useProjectsStore()

const shape = computed(() => taskStatusShape(props.task.status))
const stroke = computed(() => ({
  spinner: 'stroke-primary motion-safe:animate-spin',
  circle: 'stroke-fg-muted',
  check: 'stroke-primary',
  triangle: 'stroke-secondary',
  cross: 'stroke-diff-del-fg',
  dash: 'stroke-fg-subtle',
})[shape.value])
const project = computed(() => projects.byId(props.task.project_id)?.name ?? `Projeto ${props.task.project_id}`)
const assignee = computed(() => (props.task.assignee_agent_id !== null ? org.byId(props.task.assignee_agent_id)?.name ?? null : null))
const urgent = computed(() => props.task.priority === 'urgent' || props.task.priority === 'high')
</script>

<template>
  <RouterLink
    :to="`/tarefas/${task.id}`"
    data-test="start-task"
    class="flex min-w-0 items-start gap-3 border-t border-line px-1 py-3 text-fg no-underline hover:bg-panel focus-visible:outline-2 focus-visible:outline-primary"
  >
    <span :data-shape="shape" role="img" :aria-label="TASK_STATUS_LABELS[task.status]" class="mt-0.5 inline-flex shrink-0">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" :class="stroke" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path v-if="shape === 'spinner'" d="M12 3a9 9 0 1 1-9 9" />
        <path v-else-if="shape === 'check'" d="M5 12.5 10 17 19 7" />
        <template v-else-if="shape === 'triangle'"><path d="M12 3 2 20h20L12 3z" /><path d="M12 10v4M12 17v.01" /></template>
        <path v-else-if="shape === 'cross'" d="M6 6l12 12M18 6 6 18" />
        <path v-else-if="shape === 'dash'" d="M6 12h12" />
        <circle v-else cx="12" cy="12" r="8" />
      </svg>
    </span>
    <span class="flex min-w-0 grow flex-col gap-1">
      <span class="text-[0.8125rem] font-medium [overflow-wrap:anywhere]">{{ task.title }}</span>
      <span class="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[0.6875rem] text-fg-subtle">
        <span class="font-mono">#{{ task.id }}</span>
        <span>{{ TASK_STATUS_LABELS[task.status] }}</span>
        <span>{{ project }}</span>
        <span v-if="assignee">{{ assignee }}</span>
        <span v-if="urgent" class="text-secondary-soft">Prioridade {{ PRIORITY_LABELS[task.priority].toLocaleLowerCase('pt-BR') }}</span>
      </span>
    </span>
  </RouterLink>
</template>
