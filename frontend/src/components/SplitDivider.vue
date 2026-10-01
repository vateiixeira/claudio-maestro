<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { clampSplit, SPLIT_MAX, SPLIT_MIN } from '../projectSplitPref'

// Vertical divider between two panes. `modelValue` is the left pane's width in percent of the
// parent. `update:modelValue` fires while moving; `change` fires once a move is finished.
const props = defineProps<{ modelValue: number; label: string }>()
const emit = defineEmits<{ 'update:modelValue': [percent: number]; change: [percent: number] }>()

const STEP = 5
const divider = ref<HTMLElement | null>(null)
const dragging = ref(false)
let previousUserSelect = ''
let pointerId = -1

function onKeydown(event: KeyboardEvent) {
  const delta = event.key === 'ArrowLeft' ? -STEP : event.key === 'ArrowRight' ? STEP : 0
  if (!delta) return
  event.preventDefault()
  const next = clampSplit(props.modelValue + delta)
  emit('update:modelValue', next)
  emit('change', next)
}

function move(event: PointerEvent) {
  const rect = divider.value?.parentElement?.getBoundingClientRect()
  if (!rect || rect.width <= 0) return
  emit('update:modelValue', clampSplit(Math.round(((event.clientX - rect.left) / rect.width) * 100)))
}

function onPointerdown(event: PointerEvent) {
  const el = divider.value
  if (!el || dragging.value || event.button > 0) return
  event.preventDefault()
  dragging.value = true
  pointerId = event.pointerId
  previousUserSelect = document.body.style.userSelect
  document.body.style.userSelect = 'none'
  el.setPointerCapture?.(event.pointerId)
  el.addEventListener('pointermove', move)
  el.addEventListener('pointerup', finish)
  el.addEventListener('pointercancel', finish)
  el.addEventListener('lostpointercapture', finish)
}

function stop() {
  const el = divider.value
  if (el) {
    el.removeEventListener('pointermove', move)
    el.removeEventListener('pointerup', finish)
    el.removeEventListener('pointercancel', finish)
    el.removeEventListener('lostpointercapture', finish)
    if (el.hasPointerCapture?.(pointerId)) el.releasePointerCapture?.(pointerId)
  }
  if (dragging.value) document.body.style.userSelect = previousUserSelect
  dragging.value = false
}

function finish() {
  if (!dragging.value) return
  stop()
  emit('change', props.modelValue)
}

// Unmounting mid-drag still keeps what was dragged so far.
onBeforeUnmount(() => {
  const wasDragging = dragging.value
  stop()
  if (wasDragging) emit('change', props.modelValue)
})
</script>

<template>
  <!-- The 12px target is wider than the 1px line drawn in its middle. -->
  <div
    ref="divider"
    role="separator"
    aria-orientation="vertical"
    :aria-label="label"
    :aria-valuenow="modelValue"
    :aria-valuemin="SPLIT_MIN"
    :aria-valuemax="SPLIT_MAX"
    tabindex="0"
    data-test="split-divider"
    class="group relative z-10 -mx-1.5 flex w-3 shrink-0 cursor-col-resize touch-none items-stretch justify-center outline-none"
    @keydown="onKeydown"
    @pointerdown="onPointerdown"
  >
    <span
      class="w-px bg-line transition-colors group-hover:bg-line-strong group-focus-visible:w-0.5 group-focus-visible:bg-fg-muted"
      :class="dragging ? 'w-0.5 bg-fg-muted' : ''"
    />
  </div>
</template>
