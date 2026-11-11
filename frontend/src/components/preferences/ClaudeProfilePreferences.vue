<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { errorMessage, request } from '../../api/http'

interface ProfileState {
  active_folder: string
  default_folder: string
  selected_folder: string | null
  restart_required: boolean
}
const state = ref<ProfileState | null>(null)
const folder = ref('')
const busy = ref(true)
const error = ref<string | null>(null)
const saved = ref(false)

function accept(value: ProfileState) {
  state.value = value
  folder.value = value.selected_folder ?? ''
}
async function load() {
  busy.value = true
  error.value = null
  try {
    accept(await request<ProfileState>('GET', '/api/claude-profile'))
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}
async function save(value: string | null) {
  if (busy.value) return
  busy.value = true
  saved.value = false
  error.value = null
  try {
    accept(await request<ProfileState>('PUT', '/api/claude-profile', { folder: value }))
    saved.value = true
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}
onMounted(load)
</script>

<template>
  <section id="claude-authentication" tabindex="-1" aria-label="Pasta do Claude" class="flex flex-col gap-2 rounded-md focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-primary" :aria-busy="busy">
    <h2 class="m-0 font-mono text-xs font-normal tracking-[0.08em] text-fg-subtle uppercase">Pasta do Claude</h2>
    <p class="m-0 text-xs text-fg-muted">
      Use outra pasta, como ~/.claude-api, somente para a autenticação de API.
      Suas conversas, projetos, agentes e preferências continuam os mesmos.
      Para retornar à autenticação original, use o botão "Usar pasta padrão".
    </p>
    <p v-if="state" data-test="profile-active" class="m-0 break-all text-xs text-fg-muted">
      Autenticação em uso: <span class="font-mono">{{ state.active_folder }}</span>
    </p>
    <label for="pref-claude-folder" class="text-sm text-fg">Pasta de autenticação</label>
    <input
      id="pref-claude-folder"
      v-model="folder"
      type="text"
      autocomplete="off"
      spellcheck="false"
      placeholder="~/.claude-api"
      :disabled="busy"
      aria-describedby="pref-claude-folder-help"
      class="h-11 rounded-lg border border-line-strong bg-elevated px-3.5 font-mono text-sm text-fg outline-none placeholder:text-fg-muted focus:border-fg-muted disabled:opacity-40"
      @input="saved = false"
      @keydown.enter.prevent="save(folder)"
    />
    <p id="pref-claude-folder-help" class="m-0 text-xs text-fg-muted">
      Escolha uma pasta existente dentro da sua pasta pessoal com a chave de API no settings.json ou um apiKeyHelper configurado.
      Reinicie o Maestro para aplicar aos novos processos. O indicador de consumo da assinatura fica desligado enquanto essa pasta estiver selecionada.
    </p>
    <div class="flex flex-wrap gap-2">
      <button type="button" data-test="profile-save" :disabled="busy || !folder" class="h-11 rounded-lg border border-line-strong px-4 text-sm font-medium text-fg hover:bg-card disabled:opacity-40" @click="save(folder)">
        Salvar pasta
      </button>
      <button type="button" data-test="profile-reset" :disabled="busy" class="h-11 rounded-lg border border-line px-4 text-sm text-fg-muted hover:bg-card disabled:opacity-40" @click="save(null)">
        Usar pasta padrão
      </button>
    </div>
    <p v-if="error" role="alert" class="m-0 text-sm text-diff-del-fg">{{ error }}</p>
    <p v-if="state?.restart_required" role="status" class="m-0 text-sm text-fg-muted">
      Reinicie o Maestro para usar a autenticação de {{ state.selected_folder ?? state.default_folder }}.
      Processos já abertos mantêm a autenticação anterior até serem encerrados. O histórico permanece no mesmo lugar.
    </p>
    <p v-else-if="saved" role="status" class="m-0 text-sm text-primary-soft">Pasta salva.</p>
  </section>
</template>
