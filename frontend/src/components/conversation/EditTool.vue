<script setup lang="ts">
import { computed, ref } from 'vue'
import { diffCounts, toolDiff } from '../../conversation/diff'
import { resultText, str } from '../../conversation/tool'
import type { ToolItem } from '../../types/conversation'

const props = defineProps<{ item: ToolItem }>()

const LIMIT = 200
const lines = computed(() => toolDiff(props.item.name, props.item.input, props.item.result?.details ?? null))
const counts = computed(() => diffCounts(lines.value))
const label = computed(() => (props.item.name === 'Write' ? 'Escrita' : 'Edição'))
const showAll = ref(false)
const shown = computed(() => (showAll.value ? lines.value : lines.value.slice(0, LIMIT)))
const isError = computed(() => props.item.result?.is_error === true)
</script>

<template>
  <div class="overflow-hidden rounded-lg border border-line bg-panel">
    <div class="flex items-center gap-2 border-b border-line px-3 py-2">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 text-fg-muted" aria-hidden="true"><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></svg>
      <span class="text-xs font-semibold text-fg-muted">{{ label }}</span>
      <span class="min-w-0 grow truncate font-mono text-xs">{{ str(item.input.file_path) }}</span>
      <span v-if="!item.result" class="text-xs text-primary-soft">aplicando…</span>
      <span class="font-mono text-xs text-diff-add-fg">+{{ counts.added }}</span>
      <span class="font-mono text-xs text-diff-del-fg">−{{ counts.removed }}</span>
    </div>
    <p v-if="isError" data-test="tool-error" class="m-0 border-b border-line bg-diff-del-bg px-3 py-2 font-mono text-xs text-diff-del-fg whitespace-pre-wrap">{{ resultText(item.result?.content) }}</p>
    <div class="overflow-x-auto font-mono text-xs leading-[1.7]">
      <div
        v-for="(line, index) in shown"
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
    <button
      v-if="lines.length > LIMIT && !showAll"
      type="button"
      data-test="show-all"
      class="m-2 cursor-pointer rounded-md border border-line-strong bg-transparent px-2.5 py-1 text-xs text-primary-soft hover:bg-elevated"
      @click="showAll = true"
    >
      Ver tudo ({{ lines.length }} linhas)
    </button>
  </div>
</template>
