<script setup lang="ts">
import { onMounted, ref } from 'vue'

type BackendState = 'checking' | 'ok' | 'down'

const backend = ref<BackendState>('checking')

onMounted(async () => {
  try {
    const response = await fetch('/api/health')
    backend.value = response.ok ? 'ok' : 'down'
  } catch {
    backend.value = 'down'
  }
})
</script>

<template>
  <main class="flex h-full items-center justify-center">
    <div class="rounded-lg border border-line bg-panel px-8 py-6">
      <h1 class="text-lg font-semibold">
        <span class="text-primary">Vini7</span> Vibing
      </h1>
      <p class="mt-2 font-mono text-xs text-fg-muted">
        <span v-if="backend === 'checking'">Verificando backend…</span>
        <span v-else-if="backend === 'ok'" class="text-primary">Backend conectado</span>
        <span v-else class="text-secondary">Backend indisponível</span>
      </p>
    </div>
  </main>
</template>
