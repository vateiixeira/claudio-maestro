<script setup lang="ts">
import { computed } from 'vue'
import { AGENT_STATE_LABELS, type AgentState } from '../../org'

// The state of an agent by shape as well as color: an empty circle (idle), a circle with a green arc turning
// (running), an orange triangle (waiting for you), a dashed circle (off). The arc stops with reduced motion.
const props = withDefaults(defineProps<{ state: AgentState; size?: number }>(), { size: 14 })

const shape = computed(() => ({ idle: 'circle', busy: 'spinner', waiting: 'triangle', off: 'dashed' })[props.state])
const label = computed(() => AGENT_STATE_LABELS[props.state])
</script>

<template>
  <span
    data-test="agent-state"
    role="img"
    :aria-label="label"
    :data-state="state"
    :data-shape="shape"
    class="inline-flex shrink-0 items-center"
  >
    <svg :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <circle v-if="shape === 'circle'" cx="12" cy="12" r="8" class="stroke-fg-muted" />
      <template v-else-if="shape === 'spinner'">
        <circle cx="12" cy="12" r="8" class="stroke-primary/25" />
        <path d="M12 4a8 8 0 0 1 8 8" class="origin-center stroke-primary motion-safe:animate-spin" />
      </template>
      <template v-else-if="shape === 'triangle'">
        <path d="M12 3.5 2.5 20h19L12 3.5z" class="stroke-secondary" />
        <path d="M12 10v4M12 17v.01" class="stroke-secondary" />
      </template>
      <circle v-else cx="12" cy="12" r="8" stroke-dasharray="3 3.6" class="stroke-fg-subtle" />
    </svg>
  </span>
</template>
