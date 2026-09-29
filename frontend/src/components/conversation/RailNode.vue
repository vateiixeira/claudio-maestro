<script setup lang="ts">
import type { NodeKind } from '../../conversation/turns'

// Decorative marker of one item in the turn's rail; the card itself names the type.
defineProps<{ kind: NodeKind }>()

const SQUARE = new Set<NodeKind>(['read', 'search', 'bash', 'edit', 'task', 'tool', 'group'])
</script>

<template>
  <div data-test="rail-node" :data-kind="kind" aria-hidden="true" class="flex w-7 shrink-0 justify-center" :class="{ 'pt-1.5': kind === 'text' || kind === 'info', 'pt-px': kind === 'thinking' }">
    <span v-if="kind === 'text'" class="size-2 rounded-full bg-fg shadow-[0_0_0_4px_var(--color-bg)]" />
    <span v-else-if="kind === 'info'" class="size-2 rounded-full bg-fg-muted shadow-[0_0_0_4px_var(--color-bg)]" />
    <span v-else-if="kind === 'thinking'" class="box-border size-3.5 rounded-full border-[1.5px] border-dashed border-fg-muted bg-bg" />
    <span
      v-else
      class="box-border flex size-[26px] items-center justify-center border"
      :class="{
        'rounded-md border-line-strong bg-card text-fg': SQUARE.has(kind),
        'rounded-full border-line-strong bg-card text-fg': kind === 'agent',
        'rounded-md border-primary bg-diff-add-bg text-primary': kind === 'running',
        'rounded-md border-diff-del-fg bg-diff-del-bg text-diff-del-fg': kind === 'error',
        'rounded-md border-secondary bg-secondary-fg text-secondary': kind === 'warning',
      }"
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" :class="{ 'text-fg-muted': kind === 'task' || kind === 'tool' || kind === 'group', 'animate-spin': kind === 'running' }">
        <template v-if="kind === 'read'"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6" /></template>
        <template v-else-if="kind === 'search'"><circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.5" y2="16.5" /></template>
        <template v-else-if="kind === 'bash'"><path d="m4 17 6-6-6-6" /><line x1="12" y1="19" x2="20" y2="19" /></template>
        <template v-else-if="kind === 'edit'"><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></template>
        <template v-else-if="kind === 'task' || kind === 'group'"><line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" /><line x1="3" y1="6" x2="3.01" y2="6" /><line x1="3" y1="12" x2="3.01" y2="12" /><line x1="3" y1="18" x2="3.01" y2="18" /></template>
        <template v-else-if="kind === 'agent'"><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></template>
        <path v-else-if="kind === 'running'" d="M12 3a9 9 0 1 1-9 9" stroke-width="2.6" />
        <template v-else-if="kind === 'error'"><line x1="6" y1="6" x2="18" y2="18" stroke-width="2.4" /><line x1="18" y1="6" x2="6" y2="18" stroke-width="2.4" /></template>
        <template v-else-if="kind === 'warning'"><path d="M12 3 2 20h20L12 3z" stroke-width="2.2" /><line x1="12" y1="10" x2="12" y2="14" stroke-width="2.2" /></template>
        <path v-else d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z" />
      </svg>
    </span>
  </div>
</template>
