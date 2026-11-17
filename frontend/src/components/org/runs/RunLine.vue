<script setup lang="ts">
import { computed, ref, useId } from 'vue'
import { RouterLink } from 'vue-router'
import { OUTCOME_LABELS, SOURCE_LABELS, outcomeShape } from '../../../org'
import { formatRunningTime } from '../../../format'
import type { Run } from '../../../types/org'
import { BTN_SMALL } from '../styles'
import { durationShare, slowFactor, slowText, type RunLine } from './runDays'

// One line of the runs list of the organization: the run in a row (agent, headline, time, duration) that opens
// into its report, what woke it, its task and its conversation. Runs missed at the same minute share a line.
const props = defineProps<{
  line: RunLine
  agentName: (id: number) => string | null
  /** The longest duration, in seconds, among the runs of the list: the full width of the bars. */
  maxSeconds: number
  /** Every run of the project, to tell the slow ones from the usual. */
  all: Run[]
}>()

/** The report is cut here until the person asks for all of it. */
const SUMMARY_LIMIT = 280

const detailsId = `run-details-${useId()}`
const open = ref(false)
const fullSummary = ref(false)

const group = computed(() => (props.line.kind === 'missed' && props.line.runs.length > 1 ? props.line.runs : null))
const run = computed<Run>(() => (props.line.kind === 'run' ? props.line.run : props.line.runs[0]!))
const shape = computed(() => outcomeShape(run.value.outcome))
const label = computed(() => OUTCOME_LABELS[run.value.outcome])
const stroke = computed(() => ({
  spinner: 'stroke-primary motion-safe:animate-spin',
  circle: 'stroke-fg-muted',
  check: 'stroke-fg-muted',
  triangle: 'stroke-secondary',
  cross: 'stroke-diff-del-fg',
  dash: 'stroke-fg-subtle',
})[shape.value])

const nameOf = (id: number): string => props.agentName(id) ?? 'Agente removido'
const groupNames = computed<string[]>(() => {
  const names = [...new Set((group.value ?? []).map((r) => nameOf(r.agent_id)))]
  return names.sort((a, b) => a.localeCompare(b, 'pt-BR'))
})

const agentText = computed(() => (group.value ? `${groupNames.value.length} agentes` : nameOf(run.value.agent_id)))
const firstLine = (text: string | null): string => (text ?? '').split('\n').map((l) => l.trim()).find((l) => l !== '') ?? ''
const headline = computed(() => {
  if (group.value) {
    const names = groupNames.value
    const list = names.length > 1 ? `${names.slice(0, -1).join(', ')} e ${names[names.length - 1]}` : names[0]
    return `${group.value.length} perdidas: ${list}`
  }
  if (run.value.outcome === 'missed') return label.value
  return firstLine(run.value.summary) || firstLine(run.value.reason) || label.value
})

const time = computed(() => {
  const d = new Date(run.value.started_at * 1000)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
})
/** Missed and skipped runs never ran, so they have no duration to show. */
const timed = computed(() => !group.value && run.value.ended_at !== null && run.value.outcome !== 'missed' && run.value.outcome !== 'skipped')
const duration = computed(() =>
  run.value.ended_at === null ? null : formatRunningTime(run.value.ended_at - run.value.started_at),
)
const slow = computed(() => (group.value ? null : slowFactor(run.value, props.all)))
const barWidth = computed(() => `${durationShare(run.value, props.maxSeconds)}%`)

const summary = computed(() => (run.value.summary ?? '').trim())
const longSummary = computed(() => summary.value.length > SUMMARY_LIMIT)
const shownSummary = computed(() =>
  longSummary.value && !fullSummary.value ? `${summary.value.slice(0, SUMMARY_LIMIT).trimEnd()}…` : summary.value,
)
const reason = computed(() => (run.value.reason ?? '').trim())
const showReason = computed(() => reason.value !== '' && reason.value !== headline.value)
</script>

<template>
  <li
    data-test="run-row"
    :data-run-id="run.id"
    :data-group-size="group ? group.length : undefined"
    class="min-w-0 rounded-xl border"
    :class="open ? 'border-line-strong bg-panel' : 'border-transparent'"
  >
    <component
      :is="group ? 'div' : 'button'"
      :type="group ? undefined : 'button'"
      :data-test="group ? undefined : 'run-toggle'"
      :aria-expanded="group ? undefined : open"
      :aria-controls="group ? undefined : detailsId"
      class="grid w-full min-w-0 grid-cols-[0.875rem_minmax(0,1fr)_auto] items-center gap-x-3.5 gap-y-0.5 rounded-xl px-2.5 py-2 text-left text-sm text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary sm:grid-cols-[0.875rem_6.5rem_minmax(0,1fr)_2.75rem_7.75rem_0.875rem]"
      :class="group || open ? '' : 'hover:bg-panel'"
      @click="group ? undefined : (open = !open)"
    >
      <span data-test="run-outcome" :data-shape="shape" class="inline-flex">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" :class="stroke" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" role="img" :aria-label="group ? 'Perdidas' : label">
          <path v-if="shape === 'spinner'" d="M12 3a9 9 0 1 1-9 9" />
          <path v-else-if="shape === 'check'" d="M5 12.5 10 17 19 7" />
          <template v-else-if="shape === 'triangle'"><path d="M12 3 2 20h20L12 3z" /><path d="M12 10v4M12 17v.01" /></template>
          <path v-else-if="shape === 'cross'" d="M6 6l12 12M18 6 6 18" />
          <path v-else-if="shape === 'dash'" d="M6 12h12" />
          <circle v-else cx="12" cy="12" r="8" />
        </svg>
      </span>
      <span data-test="run-agent" class="col-start-2 row-start-1 min-w-0 truncate font-medium" :class="shape === 'dash' ? 'text-fg-muted' : 'text-fg'">{{ agentText }}</span>
      <span data-test="run-headline" :title="headline" class="col-span-2 col-start-2 row-start-2 min-w-0 truncate text-fg-muted sm:col-span-1 sm:col-start-3 sm:row-start-1">{{ headline }}</span>
      <time data-test="run-started" :datetime="new Date(run.started_at * 1000).toISOString()" class="col-start-3 row-start-1 font-mono text-xs text-fg-muted sm:col-start-4">{{ time }}</time>
      <span v-if="timed" class="col-span-2 col-start-2 row-start-3 flex items-center gap-2 sm:col-span-1 sm:col-start-5 sm:row-start-1 sm:justify-end" :title="slow ? slowText(slow) : undefined">
        <span class="block w-14 shrink-0">
          <span data-test="run-duration-bar" :data-slow="slow ? 'true' : 'false'" class="block h-[3px] min-w-[3px] rounded-full" :class="slow ? 'bg-secondary' : 'bg-line-strong'" :style="{ width: barWidth }"></span>
        </span>
        <span v-if="duration" data-test="run-duration" class="font-mono text-xs" :class="slow ? 'text-secondary' : 'text-fg-muted'">{{ duration }}</span>
      </span>
      <svg v-if="!group" class="col-start-6 row-start-1 hidden text-fg-muted sm:block" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path :d="open ? 'm6 9 6 6 6-6' : 'm9 6 6 6-6 6'" />
      </svg>
    </component>

    <div v-if="open && !group" :id="detailsId" data-test="run-details" class="flex flex-col gap-2.5 px-4 pb-3.5 pl-[2.375rem]">
      <p v-if="summary" data-test="run-summary" class="m-0 max-w-[78ch] text-[0.8125rem] leading-relaxed whitespace-pre-line text-fg-muted [overflow-wrap:anywhere]">{{ shownSummary }}</p>
      <p v-if="showReason" data-test="run-reason" class="m-0 max-w-[78ch] text-xs text-fg-muted [overflow-wrap:anywhere]">{{ reason }}</p>
      <div class="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs">
        <button v-if="longSummary" type="button" data-test="run-summary-more" :aria-expanded="fullSummary" :class="BTN_SMALL" @click="fullSummary = !fullSummary">{{ fullSummary ? 'Mostrar menos' : 'Ler o relato inteiro' }}</button>
        <span data-test="run-source" class="text-fg-muted">{{ SOURCE_LABELS[run.source] }}</span>
        <RouterLink v-if="run.task_id !== null" data-test="run-task" :to="`/tarefas/${run.task_id}`" class="rounded font-mono text-info-soft hover:underline focus-visible:outline-2 focus-visible:outline-primary">#{{ run.task_id }}</RouterLink>
        <RouterLink v-if="run.session_id" data-test="run-session" :to="`/sessions/${run.session_id}`" class="rounded text-info-soft hover:underline focus-visible:outline-2 focus-visible:outline-primary">Abrir conversa</RouterLink>
        <span v-if="slow" data-test="run-slow" class="ml-auto text-secondary">{{ slowText(slow) }}</span>
      </div>
    </div>
  </li>
</template>
