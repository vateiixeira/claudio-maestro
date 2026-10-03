<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import MarkMenu from './MarkMenu.vue'
import type { Session } from '../../types/api'

// `ignore`: the elements that opened the popover; a pointerdown on them is left to their own click, which toggles.
const props = defineProps<{ session: Session; x: number; y: number; ignore?: (HTMLElement | null)[] }>()
const emit = defineEmits<{ close: [] }>()
const root = ref<HTMLElement | null>(null)
const error = ref<string | null>(null)
const WIDTH = 248
const height = ref(0)
let opener: HTMLElement | null = null
let observer: ResizeObserver | null = null
const style = computed(() => ({
  left: `${Math.max(8, Math.min(props.x, window.innerWidth - WIDTH - 8))}px`,
  top: `${Math.max(8, Math.min(props.y, window.innerHeight - height.value - 8))}px`,
}))
const measure = () => { height.value = root.value?.offsetHeight ?? 0 }
function onKeydown(event: KeyboardEvent) {
  if (event.key !== 'Escape' || event.defaultPrevented) return
  event.preventDefault()
  emit('close')
}
function onPointerdown(event: Event) {
  const target = event.target
  if (target instanceof Node && (root.value?.contains(target) || props.ignore?.some((el) => el?.contains(target)))) return
  emit('close')
}
onMounted(() => {
  opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
  measure()
  // The date and note fields change the height; jsdom has no ResizeObserver.
  if (typeof ResizeObserver !== 'undefined' && root.value) {
    observer = new ResizeObserver(measure)
    observer.observe(root.value)
  }
  document.addEventListener('keydown', onKeydown)
  document.addEventListener('pointerdown', onPointerdown)
  root.value?.querySelector<HTMLElement>('[role^="menuitem"]')?.focus()
})
watch(() => props.y, () => nextTick(measure))
onBeforeUnmount(() => {
  observer?.disconnect()
  // Give the focus back, unless it already went somewhere else on its own.
  const active = document.activeElement
  if (opener?.isConnected && (active === document.body || (active && root.value?.contains(active)))) opener.focus()
  document.removeEventListener('keydown', onKeydown)
  document.removeEventListener('pointerdown', onPointerdown)
})
</script>

<template>
  <Teleport to="body">
    <div ref="root" data-test="mark-popover" class="fixed z-50 rounded-lg border border-line-strong bg-card shadow-lg" :style="style">
      <MarkMenu :session="session" @done="emit('close')" @error="error = $event" />
      <p v-if="error" role="alert" class="m-0 px-3 pb-2 text-xs text-diff-del-fg">{{ error }}</p>
    </div>
  </Teleport>
</template>
