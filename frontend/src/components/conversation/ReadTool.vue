<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMarkdownViewHref } from '../../conversation/markdownView'
import { countLines, resultText, str } from '../../conversation/tool'
import type { ToolItem } from '../../types/conversation'
import MarkdownViewLink from './MarkdownViewLink.vue'
import TruncatedText from './TruncatedText.vue'
import WorkHeader from './WorkHeader.vue'

// `headless`: inside a work block the row above is the header, so the card is just its body.
const props = defineProps<{ item: ToolItem; sessionActive?: boolean; headless?: boolean }>()
const open = ref(false)

const viewHref = useMarkdownViewHref(() => str(props.item.input.file_path))

const content = computed(() => resultText(props.item.result?.content))
const lineCount = computed(() => countLines(content.value))
const running = computed(() => props.item.streaming || (!props.item.result && !props.item.result_missing && props.sessionActive))
const status = computed<'ok' | 'running' | 'error' | 'idle'>(() => {
  if (running.value) return 'running'
  if (props.item.result?.is_error) return 'error'
  return props.item.result ? 'ok' : 'idle'
})
const meta = computed(() => {
  if (status.value === 'ok') return `${lineCount.value} ${lineCount.value === 1 ? 'linha' : 'linhas'}`
  return !props.item.result && !props.item.result_missing && !running.value ? 'sem resultado' : undefined
})
</script>

<template>
  <div :class="headless ? '[&>:first-child]:border-t-0' : 'overflow-hidden rounded-lg border border-line bg-panel'">
    <!-- The link sits beside the header button, never inside it: a link in a button is invalid and would toggle the card. -->
    <div v-if="!headless" class="flex items-stretch">
      <WorkHeader
        class="min-w-0 flex-1"
        kind="read"
        as="button"
        :desc="str(item.input.file_path)"
        mono
        :status="status"
        :meta="meta"
        :open="open"
        :aria-expanded="open"
        :disabled="!item.result"
        @click="open = !open"
      >
        <template v-if="item.result_missing" #trail>
          <span data-test="result-missing" class="shrink-0 text-xs text-fg-subtle">Resultado não disponível no histórico</span>
        </template>
      </WorkHeader>
      <div v-if="viewHref" class="flex shrink-0 items-center bg-[color-mix(in_oklab,var(--color-type-file)_9%,transparent)] pr-3">
        <MarkdownViewLink :href="viewHref" />
      </div>
    </div>
    <div v-if="headless && viewHref" class="flex justify-end px-3 py-1.5">
      <MarkdownViewLink :href="viewHref" />
    </div>
    <div v-if="(open || headless) && item.result" class="border-t border-line px-3 py-2" :class="{ 'text-diff-del-fg': item.result.is_error }">
      <TruncatedText :text="content" />
    </div>
  </div>
</template>
