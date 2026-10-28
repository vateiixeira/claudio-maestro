<script setup lang="ts">
import { computed } from 'vue'
import type { StateShape } from '../../../org'

// The shape of a state, drawn in the stroke color that carries the signal: an arc turning, a check, a triangle,
// a cross, a dash or an empty circle. The arc stops with reduced motion.
const props = withDefaults(defineProps<{ shape: StateShape; size?: number }>(), { size: 13 })

const tone = computed(() => ({
  spinner: 'stroke-primary motion-safe:animate-spin',
  circle: 'stroke-fg-muted',
  check: 'stroke-primary',
  triangle: 'stroke-secondary',
  cross: 'stroke-diff-del-fg',
  dash: 'stroke-fg-subtle',
})[props.shape])
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 24 24" fill="none" :class="tone" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <template v-if="shape === 'spinner'"><circle cx="12" cy="12" r="8" class="opacity-25" /><path d="M12 4a8 8 0 0 1 8 8" /></template>
    <path v-else-if="shape === 'check'" d="M5 12.5 10 17 19 7" />
    <template v-else-if="shape === 'triangle'"><path d="M12 3.5 2.5 20h19L12 3.5z" /><path d="M12 10v4M12 17v.01" /></template>
    <path v-else-if="shape === 'cross'" d="M6 6l12 12M18 6 6 18" />
    <path v-else-if="shape === 'dash'" d="M6 12h12" />
    <circle v-else cx="12" cy="12" r="8" />
  </svg>
</template>
