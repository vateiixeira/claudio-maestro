<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

defineProps<{ merging: boolean; canFetch: boolean }>()
const emit = defineEmits<{ fetch: []; abort: []; copy: []; close: [restoreFocus?: boolean] }>()
const panel = ref<HTMLElement | null>(null)

const enabledItems = () => [...(panel.value?.querySelectorAll<HTMLElement>('[role="menuitem"]:not([disabled])') ?? [])]

// On the document, not on the panel: Esc closes with the focus anywhere.
function onDocumentKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Escape') return
  event.preventDefault()
  emit('close')
}

onMounted(async () => {
  document.addEventListener('keydown', onDocumentKeydown)
  await nextTick()
  enabledItems()[0]?.focus()
})
onBeforeUnmount(() => document.removeEventListener('keydown', onDocumentKeydown))

/** Focus went to another element: the menu closes and leaves the focus where it went. */
function onFocusout(event: FocusEvent): void {
  const next = event.relatedTarget
  if (next instanceof Node && !panel.value?.contains(next)) emit('close', false)
}

function onKeydown(event: KeyboardEvent): void {
  const items = enabledItems()
  const index = items.indexOf(document.activeElement as HTMLElement)
  if (event.key === 'ArrowDown' && items.length) {
    event.preventDefault()
    items[(index + 1) % items.length].focus()
  } else if (event.key === 'ArrowUp' && items.length) {
    event.preventDefault()
    items[(index - 1 + items.length) % items.length].focus()
  }
}

const item = 'flex h-7 w-full items-center rounded px-2 text-left text-[0.8125rem] text-fg hover:bg-elevated focus:bg-elevated focus:outline-none disabled:text-fg-subtle disabled:hover:bg-transparent'
</script>

<template>
  <div class="fixed inset-0 z-40" data-test="repo-menu-backdrop" @click="emit('close')" />
  <div ref="panel" role="menu" aria-label="Mais ações" data-test="repo-menu" class="absolute top-7 right-0 z-50 flex w-56 flex-col rounded-lg border border-line-strong bg-panel p-1 shadow-2xl" @keydown="onKeydown" @focusout="onFocusout">
    <button type="button" role="menuitem" data-test="menu-fetch" :class="item" :disabled="!canFetch" @click="emit('fetch')">Buscar no remoto</button>
    <button v-if="merging" type="button" role="menuitem" data-test="menu-abort" :class="item" @click="emit('abort')">Abortar merge</button>
    <button type="button" role="menuitem" data-test="menu-copy-path" :class="item" @click="emit('copy')">Copiar caminho</button>
  </div>
</template>
