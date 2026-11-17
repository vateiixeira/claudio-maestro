<script setup lang="ts">
import { computed } from 'vue'
import { DAYS } from '../../../org'
import { nextSlot, scheduleSentence, weekSlots, type ScheduleRow } from './schedule'

// The week of a routine: the times it fires on each day, today in a tinted column and the next firing outlined.
const props = defineProps<{ schedules: ScheduleRow[]; now: Date; /** Whether the routine really fires: the next time is green only then. */ active: boolean }>()

const pad = (n: number) => String(n).padStart(2, '0')
const isoDay = (d: Date) => ((d.getDay() + 6) % 7) + 1

const today = computed(() => isoDay(props.now))
const week = computed(() => weekSlots(props.schedules))
const next = computed(() => {
  const at = nextSlot(props.schedules, props.now)
  return at ? { day: isoDay(at), time: `${pad(at.getHours())}:${pad(at.getMinutes())}` } : null
})
const label = computed(() => {
  const sentence = scheduleSentence(props.schedules)
  return `Agenda da semana: ${sentence.charAt(0).toLowerCase()}${sentence.slice(1)}`
})
</script>

<template>
  <div data-test="routine-week" role="img" :aria-label="label" class="hidden grid-cols-7 gap-x-1 lg:grid">
    <div
      v-for="(day, index) in DAYS"
      :key="day.digit"
      data-test="routine-week-day"
      :data-day="day.digit"
      :data-today="today === index + 1 ? 'true' : undefined"
      class="flex min-h-11 min-w-0 flex-col items-center gap-1 rounded-lg py-1.5"
      :class="today === index + 1 ? 'bg-panel' : ''"
    >
      <span
        v-for="time in week[index]"
        :key="time"
        data-test="routine-week-slot"
        :data-next="next && next.day === index + 1 && next.time === time ? 'true' : undefined"
        class="rounded-[5px] px-1 font-mono text-[0.65625rem] leading-[1.125rem]"
        :class="next && next.day === index + 1 && next.time === time ? (active ? 'bg-primary/20 text-primary-soft ring-1 ring-primary/45' : 'bg-elevated text-fg ring-1 ring-line-strong') : 'bg-elevated text-fg-muted'"
      >{{ time }}</span>
    </div>
  </div>
</template>
