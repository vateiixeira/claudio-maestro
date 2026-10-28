<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import TaskStatus from './TaskStatus.vue'
import { PRIORITY_LABELS } from '../../../org'
import { formatActivity } from '../../../format'
import { useOrgStore } from '../../../stores/org'
import type { Task } from '../../../types/org'

// One task of a list: number, title, status, who is responsible, the priority when it asks for attention, and when it changed.
const props = defineProps<{ task: Task; projectName?: string | null }>()
const org = useOrgStore()

const assignee = computed(() => (props.task.assignee_agent_id === null ? null : org.byId(props.task.assignee_agent_id)))
const urgent = computed(() => props.task.priority === 'urgent' || props.task.priority === 'high')
</script>

<template>
  <li class="list-none border-b border-line">
    <RouterLink
      :to="`/tarefas/${task.id}`"
      data-test="task-row"
      :data-task-id="task.id"
      class="flex min-w-0 flex-col gap-1 rounded px-1 py-2.5 text-fg no-underline hover:bg-card focus-visible:outline-2 focus-visible:outline-primary"
    >
      <span class="flex min-w-0 items-baseline gap-2">
        <span class="shrink-0 font-mono text-xs text-fg-subtle">#{{ task.id }}</span>
        <span class="min-w-0 grow text-sm font-medium [overflow-wrap:anywhere]" :class="task.status === 'cancelled' ? 'text-fg-subtle line-through' : ''">{{ task.title }}</span>
      </span>
      <span class="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1 pl-[1.6rem] text-xs text-fg-muted">
        <TaskStatus :status="task.status" />
        <span data-test="task-row-assignee" :class="assignee ? '' : 'text-fg-subtle'">{{ assignee ? assignee.name : 'Sem responsável' }}</span>
        <span v-if="urgent" data-test="task-row-priority" class="inline-flex items-center gap-1" :class="task.priority === 'urgent' ? 'font-semibold text-fg' : ''">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7" /></svg>
          {{ PRIORITY_LABELS[task.priority] }}
        </span>
        <span v-if="projectName" data-test="task-row-project" class="text-fg-subtle">{{ projectName }}</span>
        <time data-test="task-row-updated" :datetime="new Date(task.updated_at * 1000).toISOString()" class="ml-auto text-fg-subtle">{{ formatActivity(task.updated_at) }}</time>
      </span>
    </RouterLink>
  </li>
</template>
