<script setup lang="ts">
import type { DiffLine } from '../../conversation/diff'

defineProps<{ lines: DiffLine[] }>()
</script>

<template>
  <div class="overflow-x-auto font-mono text-xs leading-[1.7]">
    <div
      v-for="(line, index) in lines"
      :key="index"
      data-test="diff-line"
      :data-kind="line.kind"
      class="flex min-w-fit"
      :class="{
        'text-fg-muted': line.kind === 'context',
        'bg-diff-add-bg text-diff-add-fg': line.kind === 'add',
        'bg-diff-del-bg text-diff-del-fg': line.kind === 'del',
      }"
    >
      <span class="w-10 shrink-0 pr-2 text-right select-none">{{ line.kind === 'del' ? line.oldNo : line.newNo }}</span>
      <span class="w-4 shrink-0 select-none">{{ line.kind === 'add' ? '+' : line.kind === 'del' ? '−' : '' }}</span>
      <span class="whitespace-pre pr-3">{{ line.text }}</span>
    </div>
  </div>
</template>
