<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Routine } from '../../../types/org'
import { BTN_SMALL } from '../styles'
import { nextFireLabel, scheduleLabel } from './schedule'

// One routine of the project: what it is, who runs it, when, and the actions.
const props = defineProps<{
  routine: Routine
  agentName: string | null
  /** The clock of the "next firing" label. */
  now: Date
  busy?: boolean
  /** The answer to the last action on this row: a note, or the error of the API. */
  feedback?: { kind: 'ok' | 'error'; text: string } | null
}>()
const emit = defineEmits<{ run: []; edit: []; delete: [] }>()

const confirming = ref(false)
const next = computed(() => nextFireLabel(props.routine.schedules, props.routine.enabled, props.now))

function confirmDelete(): void {
  confirming.value = false
  emit('delete')
}
</script>

<template>
  <li data-test="routine-row" :data-routine-id="routine.id" class="flex min-w-0 flex-col gap-1.5 border-b border-line px-1 py-3">
    <div class="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
      <span data-test="routine-name-text" class="min-w-0 truncate font-medium text-fg">{{ routine.name }}</span>
      <span data-test="routine-state" class="inline-flex shrink-0 items-center gap-1 text-xs" :class="routine.enabled ? 'text-fg' : 'text-fg-subtle'">
        <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
          <circle cx="5" cy="5" r="3.5" :fill="routine.enabled ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="1.4" />
        </svg>
        {{ routine.enabled ? 'Ligada' : 'Desligada' }}
      </span>
      <span v-if="routine.create_task" data-test="routine-creates-task" class="inline-flex shrink-0 items-center gap-1 rounded border border-line px-1.5 py-0.5 text-xs text-fg-muted">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="3" /><path d="M8.5 12.5 11 15l4.5-5" /></svg>
        Cria tarefa
      </span>
      <div class="ml-auto flex shrink-0 flex-wrap items-center gap-1.5">
        <template v-if="confirming">
          <span class="text-xs text-fg-muted">Excluir esta rotina?</span>
          <button type="button" data-test="routine-delete-confirm" :class="BTN_SMALL" class="!border-diff-del-fg !text-diff-del-fg" @click="confirmDelete">Excluir</button>
          <button type="button" data-test="routine-delete-cancel" :class="BTN_SMALL" @click="confirming = false">Cancelar</button>
        </template>
        <template v-else>
          <button type="button" data-test="routine-run" :class="BTN_SMALL" :disabled="busy" @click="emit('run')">Rodar agora<span class="sr-only">: {{ routine.name }}</span></button>
          <button type="button" data-test="routine-edit" :class="BTN_SMALL" :disabled="busy" @click="emit('edit')">Editar<span class="sr-only">: {{ routine.name }}</span></button>
          <button type="button" data-test="routine-delete" :class="BTN_SMALL" :disabled="busy" @click="confirming = true">Excluir<span class="sr-only">: {{ routine.name }}</span></button>
        </template>
      </div>
    </div>

    <div class="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-fg-muted">
      <span data-test="routine-agent-name">{{ agentName ?? 'Agente removido' }}</span>
      <span data-test="routine-schedules" class="font-mono">
        <template v-if="routine.schedules.length === 0">sem horários</template>
        <template v-else>
          <template v-for="(schedule, index) in routine.schedules" :key="schedule.id">
            <span v-if="index > 0" aria-hidden="true">, </span>{{ scheduleLabel(schedule) }}
          </template>
        </template>
      </span>
      <span data-test="routine-next" class="text-fg-subtle">{{ next }}</span>
    </div>

    <p data-test="routine-instruction-text" class="m-0 truncate text-xs text-fg-subtle">{{ routine.instruction }}</p>

    <p v-if="feedback?.kind === 'error'" data-test="routine-row-error" role="alert" class="m-0 text-sm text-diff-del-fg">{{ feedback.text }}</p>
    <p v-else-if="feedback" data-test="routine-feedback" role="status" class="m-0 text-xs text-fg-muted">{{ feedback.text }}</p>
  </li>
</template>
