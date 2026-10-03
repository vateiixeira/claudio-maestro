<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

type Status = 'ok' | 'running' | 'waiting' | 'error' | 'stopped' | 'idle'

// The state at the right of a work header: done, running, waiting for the user, failed, stopped, or "idle" (nothing to say but the meta text).
const props = defineProps<{
  status: Status
  /** Short detail shown next to the state ("3 linhas"). */
  meta?: string
  /** Time spent so far, while running. */
  elapsed?: string
}>()

// A change of state cross-fades: the new one scales in while the old one fades out on top of it (absolute, so it
// takes no room). Only the active state is in the flow and readable; the one leaving is aria-hidden and goes away
// after the transition. Nothing animates on the first render, since a row that is just there has not changed.
const LEAVE_MS = 200
const leaving = ref<Status | null>(null)
const changed = ref(false)
let timer: ReturnType<typeof setTimeout> | null = null
function clearTimer() {
  if (timer) clearTimeout(timer)
  timer = null
}
watch(
  () => props.status,
  (now, before) => {
    changed.value = true
    leaving.value = before !== 'idle' && before !== now ? before : null
    clearTimer()
    if (leaving.value) timer = setTimeout(() => { leaving.value = null }, LEAVE_MS)
  },
)
onBeforeUnmount(clearTimer)

const layers = computed(() => {
  const list: { state: Status; leaving: boolean }[] = []
  if (leaving.value) list.push({ state: leaving.value, leaving: true })
  if (props.status !== 'idle') list.push({ state: props.status, leaving: false })
  return list
})
</script>

<template>
  <span data-test="work-status" :data-status="status" class="flex shrink-0 items-center gap-1.5 font-mono text-[0.6875rem] leading-none">
    <span v-if="layers.length" class="relative flex items-center">
      <span
        v-for="layer in layers"
        :key="layer.state"
        data-test="work-state-layer"
        :data-state="layer.state"
        :aria-hidden="layer.leaving ? 'true' : undefined"
        class="flex items-center gap-1.5"
        :class="layer.leaving ? 'work-state-out absolute inset-y-0 left-0' : changed ? 'work-state-in' : ''"
      >
        <template v-if="layer.state === 'ok'">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 text-primary" aria-hidden="true"><path d="M20 6 9 17l-5-5" /></svg>
          <span class="sr-only">concluído</span>
        </template>
        <template v-else-if="layer.state === 'running'">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" class="shrink-0 animate-spin text-secondary-soft motion-reduce:animate-none" aria-hidden="true"><path d="M12 3a9 9 0 1 1-9 9" stroke-linecap="round" /></svg>
          <span v-if="elapsed" data-test="work-elapsed" class="font-mono tabular-nums text-secondary-soft">{{ elapsed }}</span>
          <span class="sr-only">rodando…</span>
        </template>
        <template v-else-if="layer.state === 'waiting'">
          <!-- The same triangle with "!" as the rail node: waiting for the user is a shape, not only a color. -->
          <svg data-shape="triangle" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 text-secondary" aria-hidden="true"><path d="M12 3 2 20h20L12 3z" /><path d="M12 10v4" /><path d="M12 17h.01" /></svg>
          <span data-test="work-word" class="text-secondary-soft">esperando você</span>
        </template>
        <span v-else-if="layer.state === 'error'" data-test="work-word" class="text-diff-del-fg">falhou</span>
        <span v-else-if="layer.state === 'stopped'" data-test="work-word" class="text-fg-subtle">parado</span>
      </span>
    </span>
    <span v-if="meta" data-test="work-meta" class="text-fg-subtle">{{ meta }}</span>
  </span>
</template>

<style scoped>
@keyframes work-state-in {
  from { opacity: 0; transform: scale(.85); }
  to { opacity: 1; transform: none; }
}
@keyframes work-state-out {
  from { opacity: 1; transform: none; }
  to { opacity: 0; transform: scale(.85); }
}
.work-state-in {
  animation: work-state-in var(--motion-state) var(--ease-maestro) both;
}
.work-state-out {
  animation: work-state-out var(--motion-state) var(--ease-maestro) both;
}
</style>
