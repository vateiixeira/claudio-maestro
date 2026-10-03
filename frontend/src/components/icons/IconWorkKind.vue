<script setup lang="ts">
import type { WorkKind } from '../../conversation/work'

// The icon of a kind of action. The work header and the rail node draw it, so it is one drawing in one place.
withDefaults(defineProps<{ kind: WorkKind; size?: number }>(), { size: 13 })
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
    class="shrink-0"
    aria-hidden="true"
  >
    <template v-if="kind === 'bash'"><path d="m4 17 6-6-6-6" /><path d="M12 19h8" /></template>
    <template v-else-if="kind === 'tool'"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94z" /></template>
    <template v-else-if="kind === 'read'"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6" /></template>
    <template v-else-if="kind === 'search'"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></template>
    <template v-else-if="kind === 'edit'"><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></template>
    <template v-else><rect x="4" y="8" width="16" height="12" rx="3" /><path d="M12 8V4" /><path d="M9 14h.01" /><path d="M15 14h.01" /></template>
  </svg>
</template>
