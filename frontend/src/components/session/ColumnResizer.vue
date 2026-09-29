<script setup lang="ts">
import { onBeforeUnmount } from 'vue'
import { MAX_WIDTH, MIN_WIDTH } from '../../stores/layout'

const props = defineProps<{ width: number; label: string }>()
const emit = defineEmits<{ resize: [width: number] }>()

const STEP = 16
const BIG_STEP = 64

let startX = 0
let startWidth = 0
let dragging = false

function onMove(event: MouseEvent) {
  emit('resize', startWidth + (event.clientX - startX))
}

function stop() {
  if (!dragging) return
  dragging = false
  window.removeEventListener('pointermove', onMove)
  window.removeEventListener('pointerup', stop)
  window.removeEventListener('pointercancel', stop)
  document.body.style.removeProperty('cursor')
  document.body.style.removeProperty('user-select')
}

function onPointerDown(event: MouseEvent) {
  if (event.button !== 0) return
  event.preventDefault()
  startX = event.clientX
  startWidth = props.width
  dragging = true
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', stop)
  window.addEventListener('pointercancel', stop)
}

function onKeydown(event: KeyboardEvent) {
  const step = event.shiftKey ? BIG_STEP : STEP
  if (event.key === 'ArrowLeft') emit('resize', props.width - step)
  else if (event.key === 'ArrowRight') emit('resize', props.width + step)
  else if (event.key === 'Home') emit('resize', MIN_WIDTH)
  else return
  event.preventDefault()
}

onBeforeUnmount(stop)
</script>

<template>
  <div
    role="separator"
    aria-orientation="vertical"
    tabindex="0"
    :aria-label="label"
    :aria-valuenow="width"
    :aria-valuemin="MIN_WIDTH"
    :aria-valuemax="MAX_WIDTH"
    class="group flex w-2 shrink-0 cursor-col-resize touch-none justify-center outline-none"
    @pointerdown="onPointerDown"
    @keydown="onKeydown"
  >
    <span class="h-full w-px bg-line transition-colors group-hover:bg-primary group-focus-visible:w-0.5 group-focus-visible:bg-primary" />
  </div>
</template>
