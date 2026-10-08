<script setup lang="ts">
import type { SessionMark } from '../types/api'

withDefaults(defineProps<{ mark: SessionMark | 'priority'; size?: number }>(), { size: 11 })
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 24 24" :fill="mark === 'priority' ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <template v-if="mark === 'on_hold'"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></template>
    <template v-else-if="mark === 'blocked'"><circle cx="12" cy="12" r="9" /><path d="m5.6 5.6 12.8 12.8" /></template>
    <template v-else-if="mark === 'review'"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" /></template>
    <template v-else-if="mark === 'discarded'"><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14" /></template>
    <path v-else d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9Z" />
  </svg>
</template>
