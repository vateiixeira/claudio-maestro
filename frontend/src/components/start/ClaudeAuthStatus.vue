<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { request } from '../../api/http'
import { useEventSocket } from '../../api/socket'
import { shortPath } from '../../projectsList'

interface AuthState {
  active_source: 'default' | 'api_folder'
  active_folder: string
  default_folder: string
  selected_folder: string | null
  restart_required: boolean
}
const state = ref<AuthState | null>(null)
const loading = ref(true)
const failed = ref(false)
const socket = useEventSocket()
let ticket = 0

async function load() {
  const current = ++ticket
  loading.value = true
  failed.value = false
  try {
    const value = await request<AuthState>('GET', '/api/claude-profile')
    if (!['default', 'api_folder'].includes(value.active_source) || typeof value.active_folder !== 'string') throw new Error('Invalid auth state')
    if (current === ticket) state.value = value
  } catch {
    if (current === ticket) {
      state.value = null
      failed.value = true
    }
  } finally {
    if (current === ticket) loading.value = false
  }
}
function visible() { if (document.visibilityState === 'visible') void load() }
watch(socket.status, (status) => { if (status === 'connected') void load() })
onMounted(() => {
  void load()
  window.addEventListener('focus', load)
  document.addEventListener('visibilitychange', visible)
})
onBeforeUnmount(() => {
  ticket++
  window.removeEventListener('focus', load)
  document.removeEventListener('visibilitychange', visible)
})
</script>

<template>
  <section aria-label="Autenticação do Claude" data-test="home-auth" class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[0.8125rem]">
    <h2 class="sr-only">Autenticação do Claude</h2>
    <div class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1" aria-live="polite" :aria-busy="loading">
      <p v-if="loading" class="m-0 text-fg-muted">Consultando autenticação…</p>
      <template v-else-if="failed">
        <p class="m-0 text-fg-muted">Não foi possível consultar a autenticação.</p>
        <button type="button" data-test="auth-retry" class="min-h-9 cursor-pointer rounded-md border-0 bg-transparent px-2 text-info-soft hover:bg-card focus-visible:outline-2 focus-visible:outline-primary" @click="load">Tentar de novo</button>
      </template>
      <p v-else-if="state" data-test="auth-active" :title="state.active_folder" class="m-0 flex min-w-0 items-baseline gap-x-2 text-fg-muted">
        <span class="shrink-0">{{ state.active_source === 'api_folder' ? 'API · pasta alternativa' : 'Padrão do Claude' }}</span>
        <span class="min-w-0 truncate font-mono text-xs text-fg-subtle" :title="state.active_folder">{{ shortPath(state.active_folder) }}</span>
      </p>
    </div>
    <RouterLink data-test="auth-change" to="/preferencias?aba=geral#claude-authentication" aria-label="Trocar autenticação do Claude" class="inline-flex min-h-9 items-center rounded-md px-2 text-info-soft hover:bg-card focus-visible:outline-2 focus-visible:outline-primary">Trocar</RouterLink>
    <p v-if="!loading && !failed && state?.restart_required" data-test="auth-pending" class="m-0 basis-full break-words text-xs text-fg-muted">
      Após reiniciar: {{ state.selected_folder === null ? 'Padrão do Claude' : 'API' }} ·
      <span class="break-all font-mono">{{ state.selected_folder ?? state.default_folder }}</span>
    </p>
  </section>
</template>
