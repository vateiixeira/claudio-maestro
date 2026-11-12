<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { SESSION_ID_KEY } from '../../stores/changesPanel'
import { imageCaption, useToolImage, type ToolImageEntry } from '../../conversation/toolImages'

// The images of a result or of a work block, one at a time. Stops at the ends: no wrapping around.
const props = defineProps<{ entries: ToolImageEntry[]; start: number; sessionActive?: boolean }>()
const emit = defineEmits<{ close: [] }>()

const sessionId = inject(SESSION_ID_KEY, null)
const titleId = useId()
const panel = ref<HTMLElement | null>(null)
const closeButton = ref<HTMLButtonElement | null>(null)
const index = ref(Math.min(Math.max(props.start, 0), Math.max(props.entries.length - 1, 0)))
// The images may shrink while the viewer is open (the block's actions change): keep the position real, close when none is left.
watch(() => props.entries.length, (length) => {
  if (length === 0) emit('close')
  else if (index.value > length - 1) index.value = length - 1
})
const entry = computed(() => props.entries[index.value] ?? null)
const caption = computed(() => (entry.value ? imageCaption(entry.value.item) : ''))
const many = computed(() => props.entries.length > 1)
const { url, state } = useToolImage(() => sessionId?.value ?? null, () => entry.value, () => props.sessionActive === true)

function go(step: number): void {
  const next = index.value + step
  if (next >= 0 && next < props.entries.length) index.value = next
}

let previous: HTMLElement | null = null
onMounted(async () => {
  previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
  // On the document, not on the panel: a click on the picture sends focus to the body, and Esc and the arrows must still work.
  document.addEventListener('keydown', onKeydown)
  await nextTick()
  closeButton.value?.focus()
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  previous?.focus()
})

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.preventDefault()
    emit('close')
  } else if (event.key === 'ArrowLeft') {
    event.preventDefault()
    go(-1)
  } else if (event.key === 'ArrowRight') {
    event.preventDefault()
    go(1)
  } else if (event.key === 'Tab' && panel.value) {
    trapTab(event)
  }
}

// Keeps Tab inside the dialog.
function trapTab(event: KeyboardEvent): void {
  const items = [...panel.value!.querySelectorAll<HTMLElement>('button:not([disabled])')]
  const first = items[0]
  const last = items[items.length - 1]
  if (!first || !last) return
  if (!panel.value!.contains(document.activeElement)) {
    event.preventDefault()
    ;(event.shiftKey ? last : first).focus()
  } else if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

const arrow = 'flex size-11 shrink-0 cursor-pointer items-center justify-center rounded-full border border-line-strong bg-panel/90 text-fg hover:bg-card focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-default disabled:opacity-30 disabled:hover:bg-panel/90'
</script>

<template>
  <Teleport to="body">
    <div data-test="image-viewer-backdrop" class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-2 sm:p-4" @click.self="emit('close')">
      <section
        ref="panel"
        data-test="image-viewer"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        class="flex h-full w-full max-w-[1600px] min-w-0 flex-col gap-2"
        @click.self="emit('close')"
      >
        <header class="flex shrink-0 items-center gap-3 rounded-lg border border-line bg-panel/90 px-3 py-2">
          <h2 :id="titleId" data-test="image-viewer-caption" class="m-0 min-w-0 grow truncate text-sm font-medium text-fg">{{ caption }}</h2>
          <span v-if="many" data-test="image-viewer-counter" class="shrink-0 text-sm text-fg-muted tabular-nums">{{ index + 1 }} de {{ entries.length }}</span>
          <button ref="closeButton" type="button" data-test="image-viewer-close" aria-label="Fechar imagem" title="Fechar (Esc)" class="flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-md text-fg-muted hover:bg-card hover:text-fg focus-visible:outline-2 focus-visible:outline-primary" @click="emit('close')">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" /></svg>
          </button>
        </header>
        <div class="flex min-h-0 flex-1 items-center gap-2" @click.self="emit('close')">
          <button v-if="many" type="button" data-test="image-viewer-prev" aria-label="Imagem anterior" title="Anterior (←)" :disabled="index === 0" :class="arrow" @click="go(-1)">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m15 6-6 6 6 6" /></svg>
          </button>
          <div class="flex h-full min-w-0 flex-1 items-center justify-center" @click.self="emit('close')">
            <img v-if="url" data-test="image-viewer-image" :src="url" :alt="caption" class="max-h-full max-w-full rounded-md object-contain" />
            <p v-else-if="state === 'error'" class="m-0 rounded-md bg-panel/90 px-4 py-3 text-sm text-fg-muted">Imagem indisponível</p>
            <div v-else class="h-1/2 w-1/2 max-w-md animate-pulse rounded-md bg-panel/60" role="status" aria-label="Carregando imagem" />
          </div>
          <button v-if="many" type="button" data-test="image-viewer-next" aria-label="Próxima imagem" title="Próxima (→)" :disabled="index === entries.length - 1" :class="arrow" @click="go(1)">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 6 6 6-6 6" /></svg>
          </button>
        </div>
      </section>
    </div>
  </Teleport>
</template>
