<script setup lang="ts">
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue'
import { onCodeCopyClick } from '../../conversation/codeCopy'
import { renderMarkdown } from '../../conversation/markdown'
import { useSmoothText } from '../../conversation/useSmoothText'
import { SESSION_ID_KEY } from '../../stores/changesPanel'
import type { TextItem } from '../../types/conversation'

// The reply is running text over the background, with no box: only the work has a frame.
const props = defineProps<{ item: TextItem }>()
// Tells the conversation that the text on screen grew, so it can keep the end in view.
const emit = defineEmits<{ reveal: [] }>()

// Safe: markdown-it runs with `html: false`, so raw HTML in the text is escaped.
// While the reply streams, the markdown comes from the paced text (one render per frame at most);
// the copy button still uses the whole text that arrived.
const shown = useSmoothText(() => props.item.text, () => props.item.streaming)
// Paths to .md files in the text link to the reader page of this conversation (none outside a column).
const sessionId = inject(SESSION_ID_KEY, null)
const html = computed(() => renderMarkdown(shown.value, { sessionId: sessionId?.value }))
// After the DOM has the new text; nothing is said at mount, history appears whole.
watch(shown, () => emit('reveal'), { flush: 'post' })

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
    <div class="markdown max-w-[72ch] text-[0.9375rem] leading-[1.65]">
      <div @click="onCodeCopyClick" v-html="html" />
      <span
        v-if="item.streaming"
        data-test="streaming"
        class="ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-fg-muted align-text-bottom"
        aria-label="Escrevendo"
      />
    </div>
    <div v-if="!item.streaming" class="mt-1 flex items-center gap-2 text-[0.6875rem]">
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
