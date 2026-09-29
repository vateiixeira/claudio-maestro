<script setup lang="ts">
import { loadEverything } from '../stores/realtime'
import { useProjectsStore } from '../stores/projects'

defineProps<{ state: 'loading' | 'error' }>()

const projects = useProjectsStore()
function retry() {
  loadEverything().catch(() => {
    // The projects store keeps the error and this block shows it.
  })
}
</script>

<template>
  <p v-if="state === 'loading'" data-test="load-loading" class="m-0 py-10 text-center text-fg-muted">Carregando…</p>
  <div v-else data-test="load-error" role="alert" class="flex flex-col items-center gap-2 py-10 text-center">
    <p class="m-0 text-sm text-secondary-soft">Não foi possível carregar as conversas. {{ projects.loadError }}</p>
    <button type="button" data-test="load-retry" class="h-8 rounded-md border border-line-strong px-2.5 text-xs text-fg hover:bg-card" @click="retry">Tentar de novo</button>
  </div>
</template>
