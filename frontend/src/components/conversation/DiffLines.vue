<script setup lang="ts">
import type { DiffLine } from '../../conversation/diff'

const props = defineProps<{ lines: DiffLine[]; conflictLabels?: { ours: string; theirs: string } | null }>()

/** git's conflict markers, when the diff is of a file in conflict. */
function marker(text: string): 'ours' | 'theirs' | 'middle' | null {
  if (!props.conflictLabels) return null
  if (text.startsWith('<<<<<<< ')) return 'ours'
  if (text.startsWith('>>>>>>> ')) return 'theirs'
  return text === '=======' ? 'middle' : null
}
</script>

<template>
  <div class="overflow-x-auto font-mono text-xs leading-[1.7]">
    <div
      v-for="(line, index) in lines"
      :key="index"
      data-test="diff-line"
      :data-kind="line.kind"
      :data-marker="marker(line.text) ?? undefined"
      class="flex min-w-fit"
      :class="marker(line.text) ? 'bg-secondary-tint text-secondary' : {
        'text-fg-muted': line.kind === 'context',
        'bg-diff-add-bg text-diff-add-fg': line.kind === 'add',
        'bg-diff-del-bg text-diff-del-fg': line.kind === 'del',
      }"
    >
      <span class="w-10 shrink-0 pr-2 text-right select-none">{{ line.kind === 'del' ? line.oldNo : line.newNo }}</span>
      <span class="w-4 shrink-0 select-none">{{ marker(line.text) ? '' : line.kind === 'add' ? '+' : line.kind === 'del' ? '−' : '' }}</span>
      <span v-if="marker(line.text) === 'ours'" class="whitespace-pre pr-3">&lt;&lt;&lt;&lt;&lt;&lt;&lt; {{ conflictLabels!.ours }} <span data-test="conflict-label" class="text-fg-subtle">(sua branch)</span></span>
      <span v-else-if="marker(line.text) === 'theirs'" class="whitespace-pre pr-3">&gt;&gt;&gt;&gt;&gt;&gt;&gt; {{ conflictLabels!.theirs }} <span data-test="conflict-label" class="text-fg-subtle">(a que entra)</span></span>
      <span v-else class="whitespace-pre pr-3">{{ line.text }}</span>
    </div>
  </div>
</template>
