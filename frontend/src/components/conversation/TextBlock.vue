<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { renderMarkdown } from '../../conversation/markdown'
import type { TextItem } from '../../types/conversation'

const props = defineProps<{ item: TextItem }>()

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
    <div class="markdown">
      <div v-html="html" />
      <span
        v-if="item.streaming"
        data-test="streaming"
        class="ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-fg-muted align-text-bottom"
        aria-label="Escrevendo"
      />
    </div>
    <div v-if="!item.streaming" class="mt-1 flex items-center gap-2 text-[11px]">
      <button
        type="button"
        data-test="copy"
        aria-label="Copiar resposta"
        class="rounded-md border border-line-strong px-2 py-0.5 text-fg-muted opacity-0 transition-opacity hover:text-fg focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-primary group-hover/text:opacity-100"
        @click="copy"
      >
        Copiar
      </button>
      <span data-test="copy-status" class="text-fg-muted" aria-live="polite">{{ status }}</span>
    </div>
  </div>
</template>
