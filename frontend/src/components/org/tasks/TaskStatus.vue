<script setup lang="ts">
import { computed } from 'vue'
import ShapeIcon from './ShapeIcon.vue'
import { TASK_STATUS_LABELS, taskStatusShape } from '../../../org'
import type { TaskStatus } from '../../../types/org'

// The status of a task by shape and word, never by color alone: an empty circle (to do), a circle with an arc
// turning (in progress), a triangle (in review), a cross (blocked), a check (done), a dash (cancelled).
const props = defineProps<{ status: TaskStatus }>()

const shape = computed(() => taskStatusShape(props.status))
</script>

<template>
  <span data-test="task-status" :data-status="status" :data-shape="shape" class="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap text-xs" :class="status === 'cancelled' ? 'text-fg-subtle' : 'text-fg'">
    <ShapeIcon :shape="shape" />
    <span>{{ TASK_STATUS_LABELS[status] }}</span>
  </span>
</template>
