<script setup lang="ts">
import { computed } from 'vue'
import { deliveryTitle, formatTime, rulerLayout } from '../../deliveries'
import { useProjectsStore } from '../../stores/projects'
import type { Delivery } from '../../types/api'

// The day on a line: whole hours underneath, one dot per record in its project color, placed by its time.
// A dot scrolls to the record it stands for.
const props = defineProps<{ deliveries: Delivery[] }>()
const emit = defineEmits<{ select: [id: number] }>()

const projects = useProjectsStore()
const layout = computed(() => rulerLayout(props.deliveries))
const byId = computed(() => new Map(props.deliveries.map((d) => [d.id, d])))

const MAX_LABELS = 12
const hours = computed(() => {
  const { startHour, endHour } = layout.value
  const span = endHour - startHour
  const step = Math.max(1, Math.ceil(span / MAX_LABELS))
  const list: { hour: number; left: number }[] = []
  for (let h = startHour; h <= endHour; h += step) list.push({ hour: h, left: ((h - startHour) / span) * 100 })
  return list
})
const labelAlign = (left: number) => (left <= 0 ? '' : left >= 100 ? '-translate-x-full' : '-translate-x-1/2')

function label(id: number): string {
  const d = byId.value.get(id)!
  return `${formatTime(d.finished_at)} ${deliveryTitle(d)}`
}
function color(id: number): string | undefined {
  const projectId = byId.value.get(id)?.project_id
  return projectId == null ? undefined : projects.byId(projectId)?.color
}
// Rows stack upward from the line: each is 12px, and the dot (8px) is centered on its row.
const ROW_PX = 12
const LINE_PX = 20
const markStyle = (id: number, left: number, row: number) => {
  const background = color(id)
  return { left: `${left}%`, bottom: `${LINE_PX - 4 + row * ROW_PX}px`, ...(background ? { backgroundColor: background } : {}) }
}
</script>

<template>
  <div data-test="day-ruler" class="relative h-14 shrink-0 select-none" role="group" aria-label="Entregas ao longo do dia">
    <div class="absolute inset-x-0 border-t border-line" :style="{ bottom: `${LINE_PX}px` }" />
    <span
      v-for="h in hours"
      :key="h.hour"
      class="absolute bottom-0 text-xs text-fg-subtle tabular-nums"
      :class="labelAlign(h.left)"
      :style="{ left: `${h.left}%` }"
    >{{ h.hour }}h</span>
    <button
      v-for="m in layout.marks"
      :key="m.id"
      type="button"
      data-test="ruler-mark"
      :aria-label="label(m.id)"
      :title="label(m.id)"
      class="absolute size-2 -translate-x-1/2 rounded-full after:absolute after:-inset-1.5 after:content-[''] hover:ring-2 hover:ring-line-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
      :class="color(m.id) ? '' : 'bg-fg-subtle'"
      :style="markStyle(m.id, m.left, m.row)"
      @click="emit('select', m.id)"
    />
  </div>
</template>
