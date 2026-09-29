<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { TextItem } from '../../types/conversation'

const props = defineProps<{ item: TextItem }>()

// Open while the model thinks, closed when it ends, unless the user chose otherwise.
const manual = ref<boolean | null>(null)
const open = computed(() => manual.value ?? props.item.streaming)
function toggle() {
  manual.value = !open.value
}

// While streaming, only the last lines show, following the text as it arrives.
const TAIL_LINES = 4
const full = ref(false)
const lines = computed(() => props.item.text.replace(/\n+$/, '').split('\n'))
const windowed = computed(() => props.item.streaming && !full.value)
const shownText = computed(() => (windowed.value ? lines.value.slice(-TAIL_LINES).join('\n') : props.item.text))
const textEl = ref<HTMLElement | null>(null)
const wrapped = ref(false)
async function follow() {
  await nextTick()
  const el = textEl.value
  if (!el) return
  if (windowed.value) el.scrollTop = el.scrollHeight
  // Long lines wrap, so count what is actually cut off besides the lines dropped.
  wrapped.value = el.scrollHeight > el.clientHeight + 1
}
watch(() => [props.item.text, props.item.streaming, open.value, full.value], follow, { flush: 'post' })
onMounted(follow)
const canExpand = computed(() => props.item.streaming && open.value && (full.value || lines.value.length > TAIL_LINES || wrapped.value))
// Expanding opens the block for good; collapsing goes back to the default (closed at the end).
function toggleFull() {
  if (full.value) {
    full.value = false
    manual.value = null
  } else {
    full.value = true
    manual.value = true
  }
}

// Elapsed time, only known when this tab saw the thinking stream.
const startedAt = ref<number | null>(null)
const elapsed = ref(0)
let timer: ReturnType<typeof setInterval> | null = null
function stopTimer() {
  if (timer) clearInterval(timer)
  timer = null
}
const tick = () => {
  if (startedAt.value !== null) elapsed.value = Math.floor((Date.now() - startedAt.value) / 1000)
}
watch(
  () => props.item.streaming,
  (streaming) => {
    if (streaming && startedAt.value === null) {
      startedAt.value = Date.now()
      timer = setInterval(tick, 1000)
    } else if (!streaming) {
      tick()
      stopTimer()
    }
  },
  { immediate: true },
)
onBeforeUnmount(stopTimer)

const label = computed(() => {
  if (props.item.streaming) return `Pensando… ${elapsed.value}s`
  if (startedAt.value !== null) return `Pensou por ${elapsed.value}s`
  return 'Raciocínio'
})
</script>

<template>
  <div class="text-sm text-fg-muted">
    <button
      type="button"
      class="flex cursor-pointer items-center gap-1.5 border-none bg-transparent p-0 text-xs font-semibold text-fg-muted hover:text-fg"
      :aria-expanded="open"
      @click="toggle"
    >
      <span aria-hidden="true">{{ open ? '▾' : '▸' }}</span>
      <span :class="{ 'animate-pulse': item.streaming }">{{ label }}</span>
    </button>
    <template v-if="open">
      <p
        ref="textEl"
        data-test="thinking-text"
        class="mt-2 mb-0 whitespace-pre-wrap border-l-2 border-line-strong pl-3 leading-5 italic"
        :class="windowed ? 'max-h-20 overflow-hidden' : ''"
      >{{ shownText }}</p>
      <button
        v-if="canExpand"
        type="button"
        data-test="thinking-expand"
        class="mt-1 ml-3 cursor-pointer border-none bg-transparent p-0 text-xs font-semibold text-primary-soft hover:text-fg focus-visible:outline-2 focus-visible:outline-primary"
        :aria-expanded="full"
        @click="toggleFull"
      >{{ full ? 'Recolher' : 'Ver tudo' }}</button>
    </template>
  </div>
</template>
