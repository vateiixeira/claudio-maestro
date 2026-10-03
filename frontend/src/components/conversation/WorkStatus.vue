<script setup lang="ts">
// The state at the right of a work header: done, running, failed, stopped, or "idle" (nothing to say but the meta text).
defineProps<{
  status: 'ok' | 'running' | 'error' | 'stopped' | 'idle'
  /** Short detail shown next to the state ("3 linhas"). */
  meta?: string
  /** Time spent so far, while running. */
  elapsed?: string
}>()
</script>

<template>
  <span data-test="work-status" :data-status="status" class="flex shrink-0 items-center gap-1.5 font-mono text-[0.6875rem] leading-none">
    <template v-if="status === 'ok'">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 text-primary" aria-hidden="true"><path d="M20 6 9 17l-5-5" /></svg>
      <span class="sr-only">concluído</span>
    </template>
    <template v-else-if="status === 'running'">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" class="shrink-0 animate-spin text-secondary-soft motion-reduce:animate-none" aria-hidden="true"><path d="M12 3a9 9 0 1 1-9 9" stroke-linecap="round" /></svg>
      <span v-if="elapsed" data-test="work-elapsed" class="text-secondary-soft">{{ elapsed }}</span>
      <span class="sr-only">rodando…</span>
    </template>
    <span v-else-if="status === 'error'" data-test="work-word" class="text-diff-del-fg">falhou</span>
    <span v-else-if="status === 'stopped'" data-test="work-word" class="text-fg-subtle">parado</span>
    <span v-if="meta" data-test="work-meta" class="text-fg-subtle">{{ meta }}</span>
  </span>
</template>
