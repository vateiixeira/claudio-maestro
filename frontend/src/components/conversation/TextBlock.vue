<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { onCodeCopyClick } from '../../conversation/codeCopy'
import { renderMarkdown } from '../../conversation/markdown'
import type { TextItem } from '../../types/conversation'

// `bubble`: a reply at the top of the turn, shown as a message on the left. Nested text
// (inside a subagent or tool) stays plain, so there is no box inside a box.
const props = defineProps<{ item: TextItem; bubble?: boolean }>()

// Safe: markdown-it runs with `html: false`, so raw HTML in the text is escaped.
const html = computed(() => renderMarkdown(props.item.text))

const status = ref('')
let timer: ReturnType<typeof setTimeout> | undefined

async function copy() {
  try {
    await navigator.clipboard.writeText(props.item.text)
    status.value = 'Copiado'
  } catch {
    status.value = 'Não foi possível copiar'
  }
  clearTimeout(timer)
  timer = setTimeout(() => { status.value = '' }, 1500)
}
onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <div class="group/text">
    <div
      class="markdown max-w-[68ch]"
      :data-test="bubble ? 'assistant-bubble' : undefined"
      :class="bubble ? 'w-fit rounded-2xl rounded-tl-md border border-line bg-card px-4 py-2.5' : ''"
    >
      <div @click="onCodeCopyClick" v-html="html" />
      <span
        v-if="item.streaming"
        data-test="streaming"
        class="ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-fg-muted align-text-bottom"
        aria-label="Escrevendo"
      />
    </div>
    <div v-if="!item.streaming" class="mt-1 flex items-center gap-2 text-[11px]" :class="bubble ? 'pl-1' : ''">
      <button
        type="button"
        data-test="copy"
        aria-label="Copiar resposta"
        class="rounded-md border border-line-strong px-2 py-0.5 text-fg-muted opacity-0 pointer-events-none transition-opacity hover:text-fg focus-visible:opacity-100 focus-visible:pointer-events-auto focus-visible:outline-2 focus-visible:outline-primary group-hover/text:opacity-100 group-hover/text:pointer-events-auto group-focus-within/text:opacity-100 group-focus-within/text:pointer-events-auto [@media(hover:none)]:opacity-100 [@media(hover:none)]:pointer-events-auto"
        @click="copy"
      >
        Copiar
      </button>
      <span data-test="copy-status" class="text-fg-subtle" aria-live="polite">{{ status }}</span>
    </div>
  </div>
</template>
