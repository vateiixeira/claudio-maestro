<script setup lang="ts">
import type { ConnectionStatus } from '../types/events'

defineProps<{ status: ConnectionStatus }>()
</script>

<template>
  <div
    v-if="status === 'reconnecting'"
    role="status"
    data-test="connection-lost"
    class="flex items-start gap-2 rounded-lg border border-secondary/50 bg-elevated px-3 py-2 font-mono text-xs text-fg-subtle"
  >
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" class="mt-px shrink-0 stroke-secondary" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M12 3 2 20h20L12 3z" />
      <line x1="12" y1="10" x2="12" y2="14" />
      <line x1="12" y1="17" x2="12" y2="17.01" />
    </svg>
    Sem conexão com o servidor. Reconectando…
  </div>
</template>
