<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { TextItem } from '../../types/conversation'

const props = defineProps<{ item: TextItem }>()

// Open while the model thinks, closed when it ends, unless the user chose otherwise.
const manual = ref<boolean | null>(null)
const open = computed(() => manual.value ?? props.item.streaming)
function toggle() {
  manual.value = !open.value
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
    <p v-if="open" class="mt-2 mb-0 whitespace-pre-wrap border-l-2 border-line-strong pl-3 italic">{{ item.text }}</p>
  </div>
</template>
