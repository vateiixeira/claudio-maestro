<script setup lang="ts">
import { computed } from 'vue'
import { useSpecialistsStore } from '../../stores/specialists'

// "Agente · nome" on a session an agent started. An agent not loaded yet, or deleted since, leaves just "Agente".
const props = defineProps<{ specialistId: number }>()
const specialists = useSpecialistsStore()
const label = computed(() => {
  const name = specialists.byId(props.specialistId)?.name
  return name ? `Agente · ${name}` : 'Agente'
})
</script>

<template>
  <span data-test="agent-badge" class="shrink-0 rounded-full border border-line-strong px-1.5 font-mono text-[0.6875rem] text-fg-muted">{{ label }}</span>
</template>
