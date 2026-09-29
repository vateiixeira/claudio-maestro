<script setup lang="ts">
import { computed } from 'vue'
import type { ActivityDay, Project } from '../../types/api'

const props = defineProps<{ data: ActivityDay[]; projects: Project[]; days: number; today: Date }>()

const WIDTH = 700
const HEIGHT = 160
const GAP = 6

function iso(date: Date): string {
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${m}-${d}`
}
const short = (value: string) => `${value.slice(8, 10)}/${value.slice(5, 7)}`

const dayList = computed(() => Array.from({ length: props.days }, (_, i) => {
  const date = new Date(props.today.getFullYear(), props.today.getMonth(), props.today.getDate() - (props.days - 1 - i))
  return iso(date)
}))
const colorOf = (id: number) => props.projects.find((p) => p.id === id)?.color ?? 'var(--color-fg-muted)'
const nameOf = (id: number) => props.projects.find((p) => p.id === id)?.name ?? 'Projeto removido'
const order = computed(() => new Map(props.projects.map((p, i) => [p.id, i])))

const columns = computed(() => dayList.value.map((date) => {
  const parts = props.data
    .filter((d) => d.date === date)
    .sort((a, b) => (order.value.get(a.project_id) ?? 999) - (order.value.get(b.project_id) ?? 999))
  return { date, parts, total: parts.reduce((sum, p) => sum + p.sessions, 0) }
}))
const max = computed(() => Math.max(1, ...columns.value.map((c) => c.total)))
const barWidth = computed(() => (WIDTH - GAP * (props.days - 1)) / props.days)
const legend = computed(() => {
  const ids = new Set(props.data.map((d) => d.project_id))
  return [...ids].sort((a, b) => (order.value.get(a) ?? 999) - (order.value.get(b) ?? 999))
})

function stack(column: { parts: ActivityDay[] }) {
  let y = HEIGHT
  return column.parts.map((part) => {
    const height = (part.sessions / max.value) * (HEIGHT - 8)
    y -= height
    return { part, y, height }
  })
}
</script>

<template>
  <figure data-test="activity-chart" class="m-0 flex flex-col gap-3">
    <figcaption class="text-sm font-semibold">Atividade nos últimos {{ days }} dias</figcaption>
    <p v-if="data.length === 0" data-test="activity-empty" class="m-0 py-8 text-center text-sm text-fg-muted">Nenhuma atividade nos últimos {{ days }} dias.</p>
    <template v-else>
      <svg :viewBox="`0 0 ${WIDTH} ${HEIGHT + 20}`" class="h-44 w-full" role="img" aria-hidden="true">
        <line :x1="0" :x2="WIDTH" :y1="HEIGHT" :y2="HEIGHT" stroke="var(--color-line)" />
        <g v-for="(column, i) in columns" :key="column.date">
          <rect
            v-for="{ part, y, height } in stack(column)"
            :key="part.project_id"
            data-test="activity-bar"
            :data-date="column.date"
            :x="i * (barWidth + GAP)"
            :y="y"
            :width="barWidth"
            :height="height"
            :fill="colorOf(part.project_id)"
            rx="2"
          ><title>{{ short(column.date) }} · {{ nameOf(part.project_id) }}: {{ part.sessions }}</title></rect>
          <text v-if="i === 0 || i === columns.length - 1 || i === Math.floor(columns.length / 2)" :x="i * (barWidth + GAP) + barWidth / 2" :y="HEIGHT + 15" text-anchor="middle" font-size="11" fill="var(--color-fg-muted)">{{ short(column.date) }}</text>
        </g>
      </svg>
      <ul class="m-0 flex list-none flex-wrap gap-3 p-0 text-xs text-fg-muted">
        <li v-for="id in legend" :key="id" class="flex items-center gap-1.5"><span class="size-2 rounded-[3px]" :style="{ backgroundColor: colorOf(id) }" />{{ nameOf(id) }}</li>
      </ul>
      <table class="sr-only">
        <caption>Conversas com atividade por dia e projeto</caption>
        <thead><tr><th>Dia</th><th>Projeto</th><th>Conversas</th></tr></thead>
        <tbody>
          <tr v-for="row in data" :key="`${row.date}-${row.project_id}`"><td>{{ short(row.date) }}</td><td>{{ nameOf(row.project_id) }}</td><td>{{ row.sessions }}</td></tr>
        </tbody>
      </table>
    </template>
  </figure>
</template>
