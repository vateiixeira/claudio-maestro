<script setup lang="ts">
import { computed } from 'vue'
import IconCheck from '../icons/IconCheck.vue'
import { TASK_STATUS_LABEL, type TaskEntry } from '../../conversation/tasks'

// The session's task list at the foot of a turn. While the turn runs it is live (the task in
// progress spins); once the turn is over it stays as a quiet record, without motion.
const props = withDefaults(defineProps<{ tasks: TaskEntry[]; muted?: boolean }>(), { muted: false })

const done = computed(() => props.tasks.filter((task) => task.status === 'completed').length)
</script>

<template>
  <div
    data-test="turn-tasks"
    :data-muted="muted ? 'true' : undefined"
    role="group"
    :aria-label="`Tarefas: ${done} de ${tasks.length} concluídas`"
    class="flex flex-col gap-1.5 rounded-lg border border-line bg-panel px-3 py-2"
    :class="{ 'opacity-70': muted }"
  >
    <span data-test="turn-tasks-count" class="sr-only">{{ done }} de {{ tasks.length }}</span>
    <ul class="m-0 flex list-none flex-col gap-1.5 p-0">
      <li
        v-for="task in tasks"
        :key="task.id"
        data-test="turn-task"
        :data-status="task.status"
        class="flex items-center gap-2 text-sm"
        :title="TASK_STATUS_LABEL[task.status]"
      >
        <span
          data-test="turn-task-mark"
          class="flex shrink-0"
          :class="{
            'text-primary': task.status === 'completed',
            'text-secondary': task.status === 'in_progress',
            'animate-spin motion-reduce:animate-none': task.status === 'in_progress' && !muted,
            'text-fg-subtle': task.status === 'pending',
          }"
        >
          <IconCheck v-if="task.status === 'completed'" :size="14" />
          <svg v-else-if="task.status === 'in_progress'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="8" opacity="0.25" /><path d="M12 4a8 8 0 0 1 8 8" /></svg>
          <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="8" stroke-dasharray="3 3.2" /></svg>
        </span>
        <span
          data-test="turn-task-label"
          class="min-w-0 grow"
          :class="task.status === 'completed' ? 'text-fg-muted' : task.status === 'in_progress' ? 'font-medium text-fg' : 'text-fg'"
        >{{ task.subject }}</span>
        <span class="sr-only">{{ TASK_STATUS_LABEL[task.status] }}</span>
      </li>
    </ul>
  </div>
</template>
