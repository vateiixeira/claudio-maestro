<script setup lang="ts">
defineProps<{ text: string; muted?: boolean }>()
</script>

<template>
  <span class="inline-flex min-w-0 items-center gap-1.5 font-mono text-xs" :class="muted ? 'text-fg-muted' : 'text-fg'">
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 text-fg-muted" aria-hidden="true">
      <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /><path d="M6.5 10v4a3 3 0 0 0 3 3H14" />
    </svg>
    <span class="truncate">{{ text }}</span>
  </span>
</template>
