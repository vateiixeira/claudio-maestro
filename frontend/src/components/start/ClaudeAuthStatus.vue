<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { request } from '../../api/http'
import { useEventSocket } from '../../api/socket'

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
  <section aria-label="Autenticação do Claude" data-test="home-auth" class="flex min-w-0 flex-col gap-1.5 border-b border-line pb-4">
    <div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
      <h2 class="m-0 font-mono text-xs font-normal tracking-[0.08em] text-fg-subtle uppercase">Autenticação do Claude</h2>
      <RouterLink data-test="auth-change" to="/preferencias?aba=geral#claude-authentication" aria-label="Trocar autenticação do Claude" class="inline-flex min-h-9 items-center rounded-md px-2 text-sm text-info-soft hover:bg-card focus-visible:outline-2 focus-visible:outline-primary">Trocar</RouterLink>
    </div>
    <div aria-live="polite" :aria-busy="loading">
      <p v-if="loading" class="m-0 text-sm text-fg-muted">Consultando autenticação…</p>
      <div v-else-if="failed" class="flex flex-wrap items-center gap-2">
        <p class="m-0 text-sm text-fg-muted">Não foi possível consultar a autenticação.</p>
        <button type="button" data-test="auth-retry" class="min-h-9 rounded-md px-2 text-sm text-info-soft hover:bg-card focus-visible:outline-2 focus-visible:outline-primary" @click="load">Tentar de novo</button>
      </div>
      <template v-else-if="state">
        <p data-test="auth-active" class="m-0 flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
          <span class="font-medium text-fg">{{ state.active_source === 'api_folder' ? 'API · pasta alternativa' : 'Padrão do Claude' }}</span>
          <span class="min-w-0 break-all font-mono text-xs text-fg-muted">{{ state.active_folder }}</span>
        </p>
        <p v-if="state.restart_required" data-test="auth-pending" class="mt-2 mb-0 break-words text-xs text-fg-muted">
          Após reiniciar: {{ state.selected_folder === null ? 'Padrão do Claude' : 'API' }} ·
          <span class="break-all font-mono">{{ state.selected_folder ?? state.default_folder }}</span>
        </p>
      </template>
    </div>
  </section>
</template>
