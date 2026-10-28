<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { OUTCOME_LABELS, SOURCE_LABELS, formatRunDate, outcomeShape } from '../../../org'
import { formatRunningTime } from '../../../format'
import type { Run } from '../../../types/org'

// One run of an agent: the result by shape and word, what woke it up, its task, when it started and how long it took.
const props = defineProps<{ run: Run; agentName?: string | null }>()

const shape = computed(() => outcomeShape(props.run.outcome))
const stroke = computed(() => ({
  spinner: 'stroke-primary motion-safe:animate-spin',
  circle: 'stroke-fg-muted',
  check: 'stroke-fg-muted',
  triangle: 'stroke-secondary',
  cross: 'stroke-diff-del-fg',
  dash: 'stroke-fg-subtle',
})[shape.value])
const duration = computed(() =>
  props.run.ended_at === null ? null : formatRunningTime(props.run.ended_at - props.run.started_at),
)
</script>

<template>
  <li data-test="run-row" :data-run-id="run.id" class="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1 border-b border-line px-1 py-2.5 text-sm">
    <span data-test="run-outcome" :data-shape="shape" class="inline-flex w-36 shrink-0 items-center gap-1.5 text-fg">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" :class="stroke" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path v-if="shape === 'spinner'" d="M12 3a9 9 0 1 1-9 9" />
        <path v-else-if="shape === 'check'" d="M5 12.5 10 17 19 7" />
        <template v-else-if="shape === 'triangle'"><path d="M12 3 2 20h20L12 3z" /><path d="M12 10v4M12 17v.01" /></template>
        <path v-else-if="shape === 'cross'" d="M6 6l12 12M18 6 6 18" />
        <path v-else-if="shape === 'dash'" d="M6 12h12" />
        <circle v-else cx="12" cy="12" r="8" />
      </svg>
      <span>{{ OUTCOME_LABELS[run.outcome] }}</span>
    </span>
    <span v-if="agentName" data-test="run-agent" class="w-32 shrink-0 truncate text-fg-muted">{{ agentName }}</span>
    <span data-test="run-source" class="w-24 shrink-0 text-fg-muted">{{ SOURCE_LABELS[run.source] }}</span>
    <RouterLink v-if="run.task_id !== null" data-test="run-task" :to="`/tarefas/${run.task_id}`" class="shrink-0 rounded font-mono text-xs text-info-soft hover:underline focus-visible:outline-2 focus-visible:outline-primary">#{{ run.task_id }}</RouterLink>
    <time data-test="run-started" :datetime="new Date(run.started_at * 1000).toISOString()" class="shrink-0 font-mono text-xs text-fg-subtle">{{ formatRunDate(run.started_at) }}</time>
    <span v-if="duration" data-test="run-duration" class="shrink-0 font-mono text-xs text-fg-subtle">{{ duration }}</span>
    <span v-if="run.reason" data-test="run-reason" class="min-w-0 basis-full text-xs text-fg-muted [overflow-wrap:anywhere]">{{ run.reason }}</span>
    <RouterLink v-if="run.session_id" data-test="run-session" :to="`/sessions/${run.session_id}`" class="ml-auto shrink-0 rounded text-xs text-info-soft hover:underline focus-visible:outline-2 focus-visible:outline-primary">Abrir conversa</RouterLink>
  </li>
</template>
