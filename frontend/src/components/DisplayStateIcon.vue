<script setup lang="ts">
import type { DisplayState } from '../types/api'

// Green circle while it works, orange triangle while it waits, grey check when finished.
withDefaults(defineProps<{ display: DisplayState; size?: number }>(), { size: 12 })
</script>

<template>
  <span
    class="flex shrink-0 items-center justify-center"
    :style="{ width: `${size}px` }"
    :data-shape="display === 'running' ? 'circle' : display === 'waiting' ? 'triangle' : 'check'"
    aria-hidden="true"
  >
    <span
      v-if="display === 'running'"
      class="rounded-full bg-primary"
      :style="{ width: `${size * 0.67}px`, height: `${size * 0.67}px` }"
    />
    <svg
      v-else
      :width="size"
      :height="size"
      viewBox="0 0 24 24"
      fill="none"
      :class="display === 'waiting' ? 'stroke-secondary' : 'stroke-fg-muted'"
      stroke-width="2.4"
      stroke-linecap="round"
      stroke-linejoin="round"
    >
      <template v-if="display === 'waiting'">
        <path d="M12 3 2 20h20L12 3z" />
        <line x1="12" y1="10" x2="12" y2="14" />
        <line x1="12" y1="17" x2="12" y2="17.01" />
      </template>
      <path v-else d="M5 12.5 10 17 19 7" />
    </svg>
  </span>
</template>
