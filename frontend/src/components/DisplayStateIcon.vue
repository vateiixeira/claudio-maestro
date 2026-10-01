<script setup lang="ts">
import type { DisplayState } from '../types/api'

// Green arc spinning while it works (still under reduced motion), orange triangle while it waits, grey check when finished.
// `quiet` turns the waiting triangle grey, for lists where waiting is the common case and has nothing new.
withDefaults(defineProps<{ display: DisplayState; size?: number; quiet?: boolean }>(), { size: 12, quiet: false })
</script>

<template>
  <span
    class="flex shrink-0 items-center justify-center"
    :style="{ width: `${size}px` }"
    :data-shape="display === 'running' ? 'spinner' : display === 'waiting' ? 'triangle' : 'check'"
    aria-hidden="true"
  >
    <svg
      :width="size"
      :height="size"
      viewBox="0 0 24 24"
      fill="none"
      :class="display === 'running' ? 'stroke-primary motion-safe:animate-spin' : display === 'waiting' ? (quiet ? 'stroke-fg-subtle' : 'stroke-secondary') : 'stroke-fg-muted'"
      stroke-width="2.4"
      stroke-linecap="round"
      stroke-linejoin="round"
    >
      <path v-if="display === 'running'" d="M12 3a9 9 0 1 1-9 9" />
      <template v-else-if="display === 'waiting'">
        <path d="M12 3 2 20h20L12 3z" />
        <line x1="12" y1="10" x2="12" y2="14" />
        <line x1="12" y1="17" x2="12" y2="17.01" />
      </template>
      <path v-else d="M5 12.5 10 17 19 7" />
    </svg>
  </span>
</template>
