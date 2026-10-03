<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { TextItem } from '../../types/conversation'
import IconChevron from '../icons/IconChevron.vue'

const props = defineProps<{ item: TextItem }>()

// A finished thought with nothing in it renders nothing (the root has a v-if).
const hasText = computed(() => props.item.text.trim() !== '')

// One line shown while closed: the first thought, or the latest one while it still streams.
const preview = computed(() => {
  const filled = props.item.text.split('\n').map((l) => l.trim()).filter(Boolean)
  return (props.item.streaming ? filled[filled.length - 1] : filled[0]) ?? ''
})

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

// Elapsed time, only known when this tab saw the thinking stream (the data carries no duration). It adds up the stretches
// spent thinking: a merged block streams again when another thought arrives, and the wait
// between the two does not count.
const seen = ref(false)
const elapsed = ref(0)
let accumulated = 0
let segmentStart: number | null = null
let timer: ReturnType<typeof setInterval> | null = null
function stopTimer() {
  if (timer) clearInterval(timer)
  timer = null
}
const tick = () => {
  if (segmentStart !== null) elapsed.value = Math.floor((accumulated + Date.now() - segmentStart) / 1000)
}
watch(
  () => props.item.streaming,
  (streaming) => {
    if (streaming && segmentStart === null) {
      seen.value = true
      segmentStart = Date.now()
      timer = setInterval(tick, 1000)
    } else if (!streaming && segmentStart !== null) {
      tick()
      accumulated += Date.now() - segmentStart
      segmentStart = null
      stopTimer()
    }
  },
  { immediate: true },
)
onBeforeUnmount(stopTimer)

const label = computed(() => (props.item.streaming ? 'Pensando…' : 'Raciocínio'))
</script>

<template>
  <div
    v-if="hasText || item.streaming"
    class="rounded-md bg-[color-mix(in_oklab,var(--color-type-think)_9%,transparent)] px-2.5 py-1.5 text-sm text-fg-muted"
  >
    <component
      :is="hasText ? 'button' : 'div'"
      :type="hasText ? 'button' : undefined"
      class="flex w-full min-w-0 items-center gap-1.5 border-none bg-transparent p-0 text-left text-xs"
      :class="hasText ? 'cursor-pointer focus-visible:outline-2 focus-visible:outline-primary' : ''"
      :aria-expanded="hasText ? open : undefined"
      @click="hasText && toggle()"
    >
      <svg
        data-test="thinking-icon"
        width="13"
        height="13"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
        class="shrink-0 text-type-think"
        aria-hidden="true"
      >
        <path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5" />
        <path d="M9 18h6" />
        <path d="M10 22h4" />
      </svg>
      <span
        data-test="thinking-label"
        class="shrink-0 font-medium text-type-think"
        :class="{ 'animate-pulse motion-reduce:animate-none': item.streaming }"
      >{{ label }}</span>
      <span v-if="seen" data-test="thinking-time" class="shrink-0 font-mono text-fg-subtle">· {{ elapsed }} s</span>
      <span
        v-if="hasText && !open && preview"
        data-test="thinking-preview"
        class="min-w-0 flex-1 truncate italic text-fg-subtle"
      >{{ preview }}</span>
      <IconChevron v-if="hasText" data-test="thinking-chevron" :open="open" :size="10" class="ml-auto text-fg-subtle" />
    </component>
    <template v-if="open && hasText">
      <p
        ref="textEl"
        data-test="thinking-text"
        class="mt-2 mb-0 whitespace-pre-wrap border-l-2 border-[color-mix(in_oklab,var(--color-type-think)_45%,transparent)] pl-3 leading-5 italic text-fg-muted"
        :class="windowed ? 'max-h-20 overflow-hidden' : ''"
      >{{ shownText }}</p>
      <button
        v-if="canExpand"
        type="button"
        data-test="thinking-expand"
        class="mt-1 ml-3 cursor-pointer border-none bg-transparent p-0 text-xs font-semibold text-fg-muted hover:text-fg focus-visible:outline-2 focus-visible:outline-primary"
        :aria-expanded="full"
        @click="toggleFull"
      >{{ full ? 'Recolher' : 'Ver tudo' }}</button>
    </template>
  </div>
</template>
