<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

// One line of the compact Bash box ("IN" or "OUT"): a few lines of text cut on the
// right, a fade where there is more, a click (or Enter/Space) to open everything and
// a copy icon in the corner that only shows on hover or keyboard focus.
const props = withDefaults(
  defineProps<{ label: string; name: string; copyLabel: string; text: string; preview: number; limit?: number; error?: boolean }>(),
  { limit: 200, error: false },
)

const expanded = ref(false)
const showAll = ref(false)
const wide = ref(false)
const content = ref<HTMLElement | null>(null)

// Trailing line breaks (Bash output almost always ends in one) are not lines to show.
const body = computed(() => props.text.replace(/\n+$/, ''))
const lines = computed(() => body.value.split('\n'))
const hasMoreLines = computed(() => lines.value.length > props.preview)
const canExpand = computed(() => hasMoreLines.value || wide.value)
const previewing = computed(() => hasMoreLines.value && !expanded.value)
const limited = computed(() => expanded.value && !showAll.value && lines.value.length > props.limit)
const shown = computed(() => {
  if (!expanded.value) return lines.value.slice(0, props.preview).join('\n')
  if (limited.value) return lines.value.slice(0, props.limit).join('\n')
  return body.value
})

// A single long line has no extra lines to count: ask the browser whether it was cut.
function measure() {
  const el = content.value
  if (!el || expanded.value) return
  wide.value = el.scrollWidth > el.clientWidth + 1
}
let observer: ResizeObserver | null = null
onMounted(() => {
  measure()
  if (typeof ResizeObserver !== 'undefined' && content.value) {
    observer = new ResizeObserver(measure)
    observer.observe(content.value)
  }
})
watch(() => props.text, () => nextTick(measure))

function flip() {
  if (!canExpand.value) return
  expanded.value = !expanded.value
  showAll.value = false
  if (!expanded.value) nextTick(measure)
}
function onClick() {
  // Selecting text to copy by hand must not open or close the box.
  const sel = window.getSelection?.()
  if (sel?.toString()) {
    const inside = (n: Node | null | undefined) => !!n && !!content.value?.contains(n)
    if (inside(sel.anchorNode) || inside(sel.focusNode)) return
  }
  flip()
}

const copyState = ref<'idle' | 'done' | 'failed'>('idle')
let copyTimer: ReturnType<typeof setTimeout> | null = null
async function copy() {
  try {
    await navigator.clipboard.writeText(props.text)
    copyState.value = 'done'
  } catch {
    copyState.value = 'failed'
  }
  if (copyTimer) clearTimeout(copyTimer)
  copyTimer = setTimeout(() => (copyState.value = 'idle'), 2000)
}
onBeforeUnmount(() => {
  if (copyTimer) clearTimeout(copyTimer)
  observer?.disconnect()
})
const statusText = computed(() => ({ idle: '', done: 'Copiado', failed: 'Não foi possível copiar' })[copyState.value])
</script>

<template>
  <div class="group relative grid grid-cols-[2.25rem_minmax(0,1fr)]" role="group" :aria-label="name">
    <span class="select-none pt-1.5 pl-2.5 font-mono text-[10px] leading-4 font-semibold text-fg-subtle" aria-hidden="true">{{ label }}</span>
    <div class="relative min-w-0">
      <div
        ref="content"
        data-test="pane-toggle"
        :role="canExpand ? 'button' : undefined"
        :tabindex="canExpand ? 0 : undefined"
        :aria-expanded="canExpand ? expanded : undefined"
        :aria-label="canExpand ? `${expanded ? 'Recolher' : 'Expandir'} ${name.toLowerCase()}` : undefined"
        class="rounded-sm py-1 pr-7 pl-0 font-mono text-[11px] leading-4 outline-none focus-visible:ring-1 focus-visible:ring-primary/60"
        :class="[
          expanded ? 'whitespace-pre-wrap break-all' : 'overflow-hidden whitespace-pre',
          canExpand ? 'cursor-pointer' : '',
          error ? 'text-diff-del-fg' : 'text-fg-muted',
        ]"
        @click="onClick"
        @keydown.enter.prevent="flip"
        @keydown.space.prevent="flip"
      >{{ shown }}</div>
      <div
        v-if="!expanded && wide"
        data-test="fade-right"
        aria-hidden="true"
        class="pointer-events-none absolute inset-y-0 right-0 w-10 bg-gradient-to-r from-transparent to-panel"
      />
      <div
        v-if="previewing"
        data-test="fade"
        aria-hidden="true"
        class="pointer-events-none absolute inset-x-0 bottom-0 h-5 bg-gradient-to-b from-transparent to-panel"
      />
      <button v-if="limited" type="button" data-test="show-all" class="mb-1.5 cursor-pointer border-none bg-transparent p-0 text-[11px] text-fg-muted underline hover:text-fg" @click="showAll = true">
        Ver tudo ({{ lines.length }} linhas)
      </button>
    </div>
    <div class="absolute top-1 right-1 flex items-center gap-1">
      <span v-if="copyState !== 'idle'" data-test="copy-feedback" aria-hidden="true" class="rounded bg-panel px-1 text-[10px]" :class="copyState === 'failed' ? 'text-diff-del-fg' : 'text-fg-muted'">{{ statusText }}</span>
      <button
        type="button"
        data-test="copy"
        :aria-label="copyLabel"
        :title="copyLabel"
        class="flex h-5 w-5 cursor-pointer items-center justify-center rounded border-none bg-panel p-0 text-fg-subtle hover:text-fg focus-visible:opacity-100 group-hover:opacity-100 group-focus-within:opacity-100 [@media(hover:none)]:opacity-100"
        :class="copyState === 'idle' ? 'opacity-0' : 'opacity-100'"
        @click="copy"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>
      </button>
      <span role="status" class="sr-only">{{ statusText }}</span>
    </div>
  </div>
</template>
