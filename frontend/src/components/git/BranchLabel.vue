<script setup lang="ts">
defineProps<{ text: string; muted?: boolean }>()
</script>

<template>
  <span class="inline-flex min-w-0 items-center gap-1.5 font-mono text-xs" :class="muted ? 'text-fg-muted' : 'text-fg'">
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 text-fg-muted" aria-hidden="true">
      <circle cx="6" cy="5" r="2" /><circle cx="6" cy="19" r="2" /><circle cx="18" cy="7" r="2" />
      <path d="M6 7v10M18 9c0 5-6 4-12 8" />
    </svg>
    <span class="truncate">{{ text }}</span>
  </span>
</template>
