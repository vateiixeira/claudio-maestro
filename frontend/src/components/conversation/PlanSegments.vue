<script setup lang="ts">
import { computed } from 'vue'
import type { PlanSummary } from '../../types/api'
import { planBadge, planPosition } from '../plan/planText'

const MAX_SEGMENTS = 10

const props = defineProps<{ plan: PlanSummary; stopped?: boolean }>()

const segmented = computed(() => props.plan.total <= MAX_SEGMENTS)
const percent = computed(() => (props.plan.total > 0 ? Math.round((props.plan.done / props.plan.total) * 100) : 0))
const doneColor = computed(() => (props.stopped ? 'bg-fg-muted' : 'bg-primary'))
const currentColor = computed(() => (props.stopped ? 'bg-fg-muted/50' : 'bg-primary/50'))
const segments = computed(() =>
  Array.from({ length: props.plan.total }, (_, i) => {
    const number = i + 1
    if (number <= props.plan.done) return 'done'
    if (props.plan.current && number === props.plan.current.number) return 'current'
    return 'todo'
  }),
)
</script>

<template>
  <span data-test="plan-segments" role="img" :aria-label="planPosition(plan)" class="inline-flex shrink-0 items-center gap-2">
    <span v-if="segmented" class="inline-flex items-center gap-0.5">
      <span
        v-for="(state, i) in segments"
        :key="i"
        data-test="plan-segment"
        :data-state="state"
        class="h-[3px] w-2.5 rounded-full"
        :class="state === 'done' ? doneColor : state === 'current' ? currentColor : 'bg-line-strong'"
      />
    </span>
    <span v-else class="inline-block h-[3px] w-24 overflow-hidden rounded-full bg-line-strong">
      <span data-test="plan-segments-bar" class="block h-full rounded-full" :class="doneColor" :style="{ width: `${percent}%` }" />
    </span>
    <span aria-hidden="true" class="font-mono text-xs text-fg-muted tabular-nums">{{ planBadge(plan) }}</span>
  </span>
</template>
