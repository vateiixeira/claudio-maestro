<script setup lang="ts">
// Running and waiting counters, as in the sidebar mockup. Zero counts are hidden.
defineProps<{ running: number; waiting: number }>()
</script>

<template>
  <span v-if="running > 0" class="flex items-center gap-1 text-xs text-primary-soft" :title="`${running} em execução`">
    <span class="size-2 rounded-full bg-primary" aria-hidden="true" />
    <span data-test="count-running">{{ running }}</span>
    <span class="sr-only">em execução</span>
  </span>
  <span v-if="waiting > 0" class="flex items-center gap-1 text-xs text-secondary" :title="`${waiting} aguardando você`">
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M12 3 2 20h20L12 3z" />
      <line x1="12" y1="10" x2="12" y2="14" />
      <line x1="12" y1="17" x2="12" y2="17.01" />
    </svg>
    <span data-test="count-waiting">{{ waiting }}</span>
    <span class="sr-only">aguardando você</span>
  </span>
</template>
