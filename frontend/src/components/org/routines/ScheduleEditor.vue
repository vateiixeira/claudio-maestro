<script setup lang="ts">
import { DAYS } from '../../../org'
import { BTN, BTN_SMALL, FIELD } from '../styles'
import { toggleDay, type ScheduleRow } from './schedule'

// The weekdays and the time of each firing of a routine (local time). The parent owns the rows and saves them with
// the rest of the routine; copied from the old `AgentSchedules`, without its own save button.
const props = defineProps<{ modelValue: ScheduleRow[] }>()
/** `MAX_SCHEDULES` of the backend. */
const MAX_SCHEDULES = 50
const emit = defineEmits<{ 'update:modelValue': [rows: ScheduleRow[]] }>()

function change(index: number, changes: Partial<ScheduleRow>): void {
  emit('update:modelValue', props.modelValue.map((row, i) => (i === index ? { ...row, ...changes } : row)))
}
function add(): void {
  if (props.modelValue.length >= MAX_SCHEDULES) return
  emit('update:modelValue', [...props.modelValue, { days: '12345', time: '09:00' }])
}
function remove(index: number): void {
  emit('update:modelValue', props.modelValue.filter((_, i) => i !== index))
}
</script>

<template>
  <div data-test="schedule-editor" class="flex flex-col gap-2">
    <p v-if="modelValue.length === 0" class="m-0 text-sm text-fg-muted">Sem horários. A rotina só roda quando você pede.</p>
    <ul v-else class="m-0 flex list-none flex-col gap-2 p-0">
      <li v-for="(row, index) in modelValue" :key="index" data-test="schedule-row" class="flex flex-wrap items-center gap-2">
        <div role="group" :aria-label="`Dias do horário ${index + 1}`" class="flex gap-1">
          <button
            v-for="day in DAYS"
            :key="day.digit"
            type="button"
            data-test="day"
            :aria-pressed="row.days.includes(day.digit)"
            :aria-label="day.name"
            :title="day.name"
            class="size-8 rounded-md border text-xs font-medium focus-visible:outline-2 focus-visible:outline-primary"
            :class="row.days.includes(day.digit) ? 'border-line-strong bg-elevated text-fg' : 'border-line bg-transparent text-fg-subtle hover:bg-card'"
            @click="change(index, { days: toggleDay(row.days, day.digit) })"
          >{{ day.letter }}</button>
        </div>
        <input
          :value="row.time"
          data-test="schedule-time"
          type="time"
          :aria-label="`Hora do horário ${index + 1}`"
          :class="[FIELD, 'w-28 font-mono']"
          @input="change(index, { time: ($event.target as HTMLInputElement).value })"
        />
        <button type="button" data-test="schedule-remove" :class="BTN_SMALL" @click="remove(index)">Remover<span class="sr-only"> horário {{ index + 1 }}</span></button>
      </li>
    </ul>
    <div class="flex flex-wrap items-center gap-2">
      <button type="button" data-test="schedule-add" :class="BTN" :disabled="modelValue.length >= MAX_SCHEDULES" @click="add">Adicionar horário</button>
      <span v-if="modelValue.length >= MAX_SCHEDULES" data-test="schedule-limit" class="text-xs text-fg-muted">Limite de {{ MAX_SCHEDULES }} horários.</span>
    </div>
  </div>
</template>
