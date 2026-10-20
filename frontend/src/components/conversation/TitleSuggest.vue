<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { errorMessage, suggestSessionTitles } from '../../api/http'
import { useConversationStore } from '../../stores/conversation'
import { useSessionsStore } from '../../stores/sessions'

// Button after the title that asks the model for three titles; picking one renames the session
// exactly like the manual rename. The panel closes with Esc or a click outside, changing nothing.
const props = defineProps<{ id: string; disabled?: boolean }>()

const sessions = useSessionsStore()
const conversations = useConversationStore()

const open = ref(false)
const loading = ref(false)
const picking = ref(false)
const suggestions = ref<string[]>([])
const error = ref<string | null>(null)
// The panel grows to the right of the button; it opens toward the left only when it would spill past the right edge of the window.
const alignRight = ref(false)
const wrap = ref<HTMLElement | null>(null)
const button = ref<HTMLButtonElement | null>(null)
const PANEL_WIDTH = 320
// Every request and every closing bumps this, so an answer from an old panel is dropped.
let round = 0

async function load() {
  const mine = ++round
  loading.value = true
  error.value = null
  suggestions.value = []
  try {
    const found = await suggestSessionTitles(props.id)
    if (mine !== round) return
    suggestions.value = found
  } catch (e) {
    if (mine !== round) return
    error.value = errorMessage(e)
  } finally {
    if (mine === round) loading.value = false
  }
}

function toggle() {
  if (open.value) {
    close()
    return
  }
  const box = button.value?.getBoundingClientRect()
  alignRight.value = !!box && box.left + PANEL_WIDTH > window.innerWidth - 16
  open.value = true
  void load()
}

function close(refocus = false) {
  round++
  open.value = false
  loading.value = false
  picking.value = false
  if (refocus) button.value?.focus()
}

async function pick(value: string) {
  if (picking.value) return
  picking.value = true
  error.value = null
  try {
    await sessions.rename(props.id, value)
    const conv = conversations.get(props.id)
    if (conv) conv.title = value
    close()
  } catch (e) {
    error.value = errorMessage(e)
    picking.value = false
  }
}

function onDocumentKeydown(event: KeyboardEvent) {
  // An Esc already handled by a layer above is not ours; ours is consumed so nothing else reacts to it.
  if (event.key !== 'Escape' || event.defaultPrevented) return
  event.preventDefault()
  close(true)
}
function onDocumentPointerdown(event: Event) {
  if (wrap.value && event.target instanceof Node && wrap.value.contains(event.target)) return
  close()
}
function removeListeners() {
  document.removeEventListener('keydown', onDocumentKeydown)
  document.removeEventListener('pointerdown', onDocumentPointerdown)
}
watch(open, (isOpen) => {
  removeListeners()
  if (!isOpen) return
  document.addEventListener('keydown', onDocumentKeydown)
  document.addEventListener('pointerdown', onDocumentPointerdown)
})
onBeforeUnmount(() => {
  round++
  removeListeners()
})
</script>

<template>
  <div ref="wrap" class="relative shrink-0">
    <button
      ref="button"
      type="button"
      data-test="suggest-title"
      aria-label="Sugerir título"
      title="Sugerir título"
      aria-haspopup="true"
      :aria-expanded="open"
      :disabled="disabled"
      class="flex size-8 items-center justify-center rounded-md text-fg-muted hover:bg-card hover:text-fg focus-visible:outline-2 focus-visible:outline-primary disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-fg-muted"
      @click="toggle"
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 4l2 6 6 2-6 2-2 6-2-6-6-2 6-2Z" /><path d="M19 3v4" /><path d="M17 5h4" /><path d="M19 17v4" /><path d="M17 19h4" /></svg>
    </button>
    <div
      v-if="open"
      data-test="title-suggest-panel"
      aria-label="Sugestões de título"
      class="absolute top-full z-20 mt-1 flex w-80 max-w-[calc(100vw-2rem)] flex-col rounded-lg border border-line-strong bg-card py-1 shadow-lg"
      :class="alignRight ? 'right-0' : 'left-0'"
    >
      <p v-if="loading" role="status" class="m-0 px-3 py-2 text-sm text-fg-muted">Gerando sugestões…</p>
      <ul v-else-if="suggestions.length > 0" class="m-0 flex list-none flex-col p-0">
        <li v-for="suggestion in suggestions" :key="suggestion">
          <button
            type="button"
            data-test="title-suggestion"
            class="block w-full px-3 py-2 text-left text-sm hover:bg-elevated focus:bg-elevated focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-fg-muted disabled:opacity-40"
            :disabled="picking"
            @click="pick(suggestion)"
          >{{ suggestion }}</button>
        </li>
      </ul>
      <p v-if="error" data-test="title-suggest-error" role="alert" class="m-0 px-3 py-2 text-sm text-diff-del-fg">{{ error }}</p>
      <div class="mt-1 border-t border-line px-1 pt-1">
        <button
          type="button"
          data-test="suggest-again"
          class="block w-full rounded-md px-2 py-1.5 text-left text-xs text-fg-muted hover:bg-elevated hover:text-fg focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-fg-muted disabled:opacity-40"
          :disabled="loading || picking"
          @click="load"
        >{{ suggestions.length > 0 ? 'Gerar outras' : 'Tentar de novo' }}</button>
      </div>
    </div>
  </div>
</template>
