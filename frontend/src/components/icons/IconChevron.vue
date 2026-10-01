<script setup lang="ts">
// Points right when closed and turns down (90°) when `open`; the turn is skipped under reduced motion.
withDefaults(defineProps<{ open?: boolean; size?: number }>(), { open: false, size: 14 })
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    class="shrink-0 motion-safe:transition-transform"
    :class="open ? 'rotate-90' : ''"
    :data-open="open"
    aria-hidden="true"
  >
    <path d="m9 18 6-6-6-6" />
  </svg>
</template>
