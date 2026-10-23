<script setup lang="ts">
import { computed } from 'vue'
import { OUTCOME_LABELS, outcomeShape } from '../../agents'
import type { SpecialistRunOutcome } from '../../types/api'

// The state of a run by shape as well as color: a green arc turning (running), a grey check (concluded, closed),
// an orange triangle with "!" (waiting for you), a red cross (failed), a grey dash (skipped, missed).
// With no run yet, a faint empty circle.
const props = withDefaults(defineProps<{ outcome: SpecialistRunOutcome | null; size?: number; showLabel?: boolean }>(), { size: 12, showLabel: false })

const shape = computed(() => (props.outcome ? outcomeShape(props.outcome) : 'none'))
const label = computed(() => (props.outcome ? OUTCOME_LABELS[props.outcome] : 'Sem execuções'))
const stroke = computed(() => ({
  spinner: 'stroke-primary motion-safe:animate-spin',
  check: 'stroke-fg-muted',
  triangle: 'stroke-secondary',
  cross: 'stroke-diff-del-fg',
  dash: 'stroke-fg-subtle',
  none: 'stroke-fg-subtle/60',
})[shape.value])
</script>

<template>
  <span class="inline-flex shrink-0 items-center gap-1.5" :data-shape="shape">
    <svg :width="size" :height="size" viewBox="0 0 24 24" fill="none" :class="stroke" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path v-if="shape === 'spinner'" d="M12 3a9 9 0 1 1-9 9" />
      <path v-else-if="shape === 'check'" d="M5 12.5 10 17 19 7" />
      <template v-else-if="shape === 'triangle'">
        <path d="M12 3 2 20h20L12 3z" /><line x1="12" y1="10" x2="12" y2="14" /><line x1="12" y1="17" x2="12" y2="17.01" />
      </template>
      <path v-else-if="shape === 'cross'" d="M6 6l12 12M18 6 6 18" />
      <path v-else-if="shape === 'dash'" d="M6 12h12" />
      <circle v-else cx="12" cy="12" r="7" stroke-dasharray="3 4" />
    </svg>
    <span :class="showLabel ? '' : 'sr-only'">{{ label }}</span>
  </span>
</template>
