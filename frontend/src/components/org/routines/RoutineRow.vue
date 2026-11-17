<script setup lang="ts">
import { computed, ref } from 'vue'
import { OUTCOME_LABELS, formatRunDate, outcomeShape } from '../../../org'
import { formatRunningTime } from '../../../format'
import type { Routine, Run } from '../../../types/org'
import MoreMenu from '../../ui/MoreMenu.vue'
import ToggleSwitch from '../../ui/ToggleSwitch.vue'
import RunHistory from '../RunHistory.vue'
import { BTN_SMALL } from '../styles'
import RoutineWeek from './RoutineWeek.vue'
import { nextSlot, scheduleSentence, slotLabel } from './schedule'

// One routine of the project: the switch, who runs it and when, the next and the last firing, and the actions.
const props = defineProps<{
  routine: Routine
  /** Null when the agent was removed. */
  agentName: string | null
  /** Whether the agent is on; null when the agent was removed. */
  agentEnabled: boolean | null
  /** The runs of this routine, newest first. */
  runs: Run[]
  /** The clock of the "next firing" label. */
  now: Date
  busy?: boolean
  /** The answer to the last action on this row: a note, or the error of the API. */
  feedback?: { kind: 'ok' | 'error'; text: string } | null
}>()
const emit = defineEmits<{ run: []; edit: []; delete: []; toggle: [enabled: boolean] }>()

const confirming = ref(false)

const sentence = computed(() => scheduleSentence(props.routine.schedules))
const hasSchedule = computed(() => props.routine.schedules.length > 0)
const next = computed(() => {
  const at = nextSlot(props.routine.schedules, props.now)
  return at ? slotLabel(at, props.now) : 'sem horário'
})
/** Why the next firing will not happen, when it will not. */
const blocked = computed<string | null>(() => {
  if (!hasSchedule.value) return null
  if (!props.routine.enabled) return 'não roda: rotina desligada'
  if (props.agentEnabled === null) return 'não roda: agente removido'
  if (!props.agentEnabled) return 'não roda: agente desligado'
  return null
})

const last = computed<Run | null>(() => props.runs.reduce<Run | null>((best, run) => (!best || run.started_at > best.started_at ? run : best), null))
const lastShape = computed(() => (last.value ? outcomeShape(last.value.outcome) : null))
const lastStroke = computed(() => ({
  spinner: 'stroke-primary motion-safe:animate-spin',
  circle: 'stroke-fg-muted',
  check: 'stroke-primary-soft',
  triangle: 'stroke-secondary',
  cross: 'stroke-diff-del-fg',
  dash: 'stroke-fg-muted',
})[lastShape.value ?? 'dash'])
const lastDate = computed(() => (last.value ? formatRunDate(last.value.started_at, props.now) : ''))
const lastOutcome = computed(() => {
  const outcome = last.value?.outcome
  if (!outcome || outcome === 'concluded' || outcome === 'closed') return null
  return OUTCOME_LABELS[outcome].toLowerCase()
})
const lastDuration = computed(() => {
  const run = last.value
  if (!run || run.ended_at === null || run.outcome === 'missed' || run.outcome === 'skipped') return null
  return formatRunningTime(run.ended_at - run.started_at)
})

function confirmDelete(): void {
  confirming.value = false
  emit('delete')
}
</script>

<template>
  <li
    data-test="routine-row"
    :data-routine-id="routine.id"
    class="grid min-w-0 grid-cols-[2.125rem_minmax(0,1fr)] gap-x-4 border-b border-line py-5 lg:grid-cols-[2.125rem_minmax(0,1fr)_20.125rem]"
  >
    <ToggleSwitch
      data-test="routine-toggle"
      :model-value="routine.enabled"
      :label="`Rotina ${routine.name}`"
      :disabled="busy"
      class="mt-0.5"
      @update:model-value="emit('toggle', $event)"
    />

    <div class="flex min-w-0 flex-col gap-1.5">
      <div class="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1">
        <h3 data-test="routine-name-text" class="m-0 min-w-0 truncate text-base font-semibold text-fg">{{ routine.name }}</h3>
        <span data-test="routine-agent-name" class="shrink-0 font-mono text-xs text-fg-muted">{{ agentName === null ? 'Agente removido' : `agente ${agentName}` }}</span>
        <span v-if="routine.create_task" data-test="routine-creates-task" class="inline-flex shrink-0 items-center gap-1 rounded border border-line px-1.5 py-0.5 text-xs text-fg-muted">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="3" /><path d="M8.5 12.5 11 15l4.5-5" /></svg>
          Cria tarefa
        </span>
      </div>

      <p data-test="routine-schedules" class="m-0 text-sm text-fg">{{ sentence }}</p>
      <p data-test="routine-instruction-text" class="m-0 truncate text-xs text-fg-muted">Instrução: {{ routine.instruction }}</p>

      <div class="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-fg-muted">
        <span class="font-semibold tracking-wide text-primary-soft uppercase">Próxima</span>
        <span data-test="routine-next" class="text-fg">{{ next }}</span>
        <span v-if="blocked" data-test="routine-blocked" class="text-secondary-soft">{{ blocked }}</span>
      </div>
      <div data-test="routine-last" class="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-fg-muted">
        <span class="font-semibold tracking-wide uppercase">Última</span>
        <template v-if="last">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" :class="lastStroke" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" role="img" :aria-label="OUTCOME_LABELS[last.outcome]">
            <path v-if="lastShape === 'spinner'" d="M12 3a9 9 0 1 1-9 9" />
            <path v-else-if="lastShape === 'check'" d="M5 12.5 10 17 19 7" />
            <template v-else-if="lastShape === 'triangle'"><path d="M12 3 2 20h20L12 3z" /><path d="M12 10v4M12 17v.01" /></template>
            <path v-else-if="lastShape === 'cross'" d="M6 6l12 12M18 6 6 18" />
            <path v-else-if="lastShape === 'dash'" d="M6 12h12" />
            <circle v-else cx="12" cy="12" r="8" />
          </svg>
          <span>{{ lastDate }}<template v-if="lastOutcome">, {{ lastOutcome }}</template></span>
          <span v-if="lastDuration" class="font-mono">{{ lastDuration }}</span>
          <RunHistory :runs="runs" class="ml-1.5" />
        </template>
        <span v-else>ainda não rodou</span>
      </div>

      <div class="mt-2 flex flex-wrap items-center gap-2">
        <template v-if="confirming">
          <span class="text-xs text-fg-muted">Excluir esta rotina?</span>
          <button type="button" data-test="routine-delete-confirm" :class="BTN_SMALL" class="!border-diff-del-fg !text-diff-del-fg" @click="confirmDelete">Excluir</button>
          <button type="button" data-test="routine-delete-cancel" :class="BTN_SMALL" @click="confirming = false">Cancelar</button>
        </template>
        <template v-else>
          <button type="button" data-test="routine-run" :class="BTN_SMALL" :disabled="busy" @click="emit('run')">Rodar agora<span class="sr-only">: {{ routine.name }}</span></button>
          <button type="button" data-test="routine-edit" :class="BTN_SMALL" :disabled="busy" @click="emit('edit')">Editar<span class="sr-only">: {{ routine.name }}</span></button>
          <MoreMenu
            data-test="routine-more"
            :label="`Mais ações da rotina ${routine.name}`"
            :items="[{ id: 'delete', label: 'Excluir', danger: true, disabled: busy }]"
            @select="confirming = true"
          />
        </template>
      </div>

      <p v-if="feedback?.kind === 'error'" data-test="routine-row-error" role="alert" class="m-0 text-sm text-diff-del-fg">{{ feedback.text }}</p>
      <p v-else-if="feedback" data-test="routine-feedback" role="status" class="m-0 text-xs text-fg-muted">{{ feedback.text }}</p>
    </div>

    <RoutineWeek :schedules="routine.schedules" :now="now" />
  </li>
</template>
