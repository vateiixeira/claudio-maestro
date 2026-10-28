<script setup lang="ts">
import { computed } from 'vue'
import { useOrgStore } from '../../stores/org'

// "Agente · nome" on a session an agent started. An agent not loaded yet, or deleted since, leaves just "Agente".
const props = defineProps<{ agentId: number }>()
const org = useOrgStore()
const label = computed(() => {
  const name = org.byId(props.agentId)?.name
  return name ? `Agente · ${name}` : 'Agente'
})
</script>

<template>
  <span data-test="agent-badge" :title="label" class="max-w-48 shrink-0 truncate rounded-full border border-line-strong px-1.5 font-mono text-[0.6875rem] text-fg-muted">{{ label }}</span>
</template>
