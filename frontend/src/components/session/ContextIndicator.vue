<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { formatTokens } from '../../format'
import type { ContextUsage } from '../../types/api'
import ContextBreakdown from '../context/ContextBreakdown.vue'

const props = defineProps<{ sessionId: string; context: ContextUsage }>()

const percent = computed(() => Math.round(props.context.percent))
const title = computed(
  // "1 milhão de tokens", but "200 mil tokens".
  () => `${formatTokens(props.context.used_tokens)} de ${formatTokens(props.context.max_tokens)}${props.context.max_tokens >= 1_000_000 ? ' de' : ''} tokens`,
)
const warn = computed(() => percent.value >= 80)
// The ring fills with the real share, never past the full circle.
const ring = computed(() => `conic-gradient(currentColor ${Math.min(Math.max(props.context.percent, 0), 100)}%, var(--color-line-strong) 0)`)

const open = ref(false)
const trigger = ref<HTMLButtonElement | null>(null)
const popover = ref<HTMLElement | null>(null)

const GAP = 6 // between the indicator and the popover
const MARGIN = 8 // kept free at the viewport edges

// Teleported to <body> with position: fixed, like OptionMenu: no ancestor's overflow clips it.
function place() {
  const button = trigger.value
  const panel = popover.value
  if (!button || !panel) return
  const rect = button.getBoundingClientRect()
  const viewportWidth = window.innerWidth
  const viewportHeight = window.innerHeight
  const above = rect.top - GAP - MARGIN
  const below = viewportHeight - rect.bottom - GAP - MARGIN
  const needed = panel.scrollHeight + 2
  const up = needed <= above || (needed > below && above >= below)
  const left = Math.max(MARGIN, Math.min(rect.left, viewportWidth - panel.offsetWidth - MARGIN))
  const style = panel.style
  style.left = `${left}px`
  style.top = up ? '' : `${rect.bottom + GAP}px`
  style.bottom = up ? `${viewportHeight - rect.top + GAP}px` : ''
  style.maxHeight = `${Math.max(0, up ? above : below)}px`
  style.visibility = ''
}

async function show() {
  open.value = true
  document.addEventListener('pointerdown', onOutside)
  document.addEventListener('keydown', onKey, true)
  window.addEventListener('resize', onResize)
  window.addEventListener('scroll', onScroll, true)
  await nextTick()
  place()
  popover.value?.focus()
}

function removeListeners() {
  document.removeEventListener('pointerdown', onOutside)
  document.removeEventListener('keydown', onKey, true)
  window.removeEventListener('resize', onResize)
  window.removeEventListener('scroll', onScroll, true)
}

function hide(returnFocus = true) {
  open.value = false
  removeListeners()
  if (returnFocus) trigger.value?.focus()
}

function onOutside(event: Event) {
  const target = event.target as Node
  if (!trigger.value?.contains(target) && !popover.value?.contains(target)) hide(false)
}
function onKey(event: KeyboardEvent) {
  if (event.key !== 'Escape' || event.defaultPrevented) return
  // Capture phase: the popover consumes this Esc before the window listeners of the conversation (drawer) see it.
  event.preventDefault()
  event.stopPropagation()
  hide()
}
function onResize() {
  hide(!!popover.value?.contains(document.activeElement))
}
function onScroll(event: Event) {
  const target = event.target as Node | null
  const button = trigger.value
  // Scrolling the popover's own lists is fine, and so is anything that does not carry the indicator along.
  if (!button || (target && popover.value?.contains(target))) return
  const moved = !target || target === document || target === document.documentElement || target.contains(button)
  if (!moved) return
  const rect = button.getBoundingClientRect()
  const visible = rect.bottom > 0 && rect.top < window.innerHeight && rect.right > 0 && rect.left < window.innerWidth
  if (visible) place()
  else hide(!!popover.value?.contains(document.activeElement))
}
onBeforeUnmount(removeListeners)

function toggle() {
  if (open.value) hide()
  else void show()
}
</script>

<template>
  <div class="relative">
    <button
      ref="trigger"
      type="button"
      data-test="context-usage"
      :title="title"
      :aria-label="`Contexto ${percent}%, ${title}`"
      aria-haspopup="dialog"
      :aria-expanded="open"
      class="flex h-9 cursor-pointer items-center gap-1.5 rounded-md border-0 bg-transparent px-1.5 font-mono text-xs hover:text-fg focus-visible:outline-2 focus-visible:outline-primary"
      :class="warn ? 'text-secondary' : 'text-fg-subtle'"
      @click="toggle"
    >
      <span
        aria-hidden="true"
        class="block size-4 shrink-0 rounded-full"
        :style="{ background: ring, mask: 'radial-gradient(farthest-side, transparent calc(100% - 2.5px), #000 calc(100% - 2px))', WebkitMask: 'radial-gradient(farthest-side, transparent calc(100% - 2.5px), #000 calc(100% - 2px))' }"
      />
      <span aria-hidden="true">{{ percent }}%</span>
    </button>
    <Teleport to="body">
      <div
        v-if="open"
        ref="popover"
        data-test="context-popover"
        role="dialog"
        aria-label="Detalhamento do contexto"
        tabindex="-1"
        style="position: fixed; visibility: hidden"
        class="z-[60] w-[min(22rem,calc(100vw-1rem))] overflow-y-auto rounded-lg border border-line-strong bg-card p-3 shadow-lg focus:outline-none"
      >
        <ContextBreakdown :session-id="sessionId" :context="context" variant="popover" />
      </div>
    </Teleport>
  </div>
</template>
