<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { errorMessage, getGithubSettings, putGithubSettings } from '../../api/http'
import type { GithubSettings } from '../../types/api'
import { BTN, BTN_PRIMARY, ERROR, FIELD } from './styles'

const state = ref<GithubSettings | null>(null)
const login = ref('')
const secret = ref('')
const changingSecret = ref(false)
const loading = ref(true)
const saving = ref(false)
const error = ref<string | null>(null)
const saved = ref(false)
async function load() {
  loading.value = true
  error.value = null
  try {
    state.value = await getGithubSettings()
    login.value = state.value.login ?? ''
    changingSecret.value = !state.value.secret_set
  } catch (e) { error.value = errorMessage(e) }
  finally { loading.value = false }
}
async function save() {
  if (saving.value) return
  saving.value = true
  error.value = null
  saved.value = false
  try {
    state.value = await putGithubSettings({ login: login.value.trim(), ...(changingSecret.value && secret.value ? { secret: secret.value } : {}) })
    secret.value = ''
    changingSecret.value = !state.value.secret_set
    saved.value = true
  } catch (e) { error.value = errorMessage(e) }
  finally { saving.value = false }
}
onMounted(load)
</script>

<template>
  <section aria-labelledby="github-settings-title" class="flex max-w-prose flex-col gap-4">
    <h2 id="github-settings-title" class="m-0 font-mono text-xs font-medium tracking-wide text-fg-subtle uppercase">Comentários do GitHub</h2>
    <p class="m-0 text-sm leading-relaxed text-fg-muted">Comentários seus nos PRs abertos pelos agentes voltam à conversa que abriu o PR. O agente responde por aqui.</p>
    <p v-if="loading" role="status" class="m-0 text-sm text-fg-subtle">Carregando configuração…</p>
    <form v-else-if="state" class="flex flex-col gap-4" @submit.prevent="save">
      <label class="flex flex-col gap-1.5 text-sm">Login do GitHub
        <input v-model="login" data-test="github-login" :class="FIELD" maxlength="39" autocomplete="off" :disabled="saving" @input="saved = false" />
      </label>
      <div class="flex flex-col gap-1.5 text-sm">
        <label v-if="changingSecret" for="github-webhook-secret">Segredo do webhook</label>
        <input v-if="changingSecret" id="github-webhook-secret" v-model="secret" data-test="github-secret" type="password" :class="FIELD" autocomplete="new-password" :disabled="saving" @input="saved = false" />
        <div v-else class="flex items-center gap-3"><span>Segredo do webhook: definido</span><button type="button" data-test="github-secret-change" :class="BTN" @click="changingSecret = true; saved = false">Trocar</button></div>
      </div>
      <p class="m-0 text-xs text-fg-subtle">{{ state.hooks_port ? `Recebendo na porta ${state.hooks_port}` : 'Receptor desligado (defina MAESTRO_HOOKS_PORT)' }} · {{ state.queued }} {{ state.queued === 1 ? 'comentário na fila' : 'comentários na fila' }}</p>
      <div class="flex items-center gap-3"><button type="submit" :class="BTN_PRIMARY" :disabled="saving">{{ saving ? 'Salvando…' : 'Salvar' }}</button><span v-if="saved" role="status" class="text-sm text-primary-soft">Salvo</span></div>
    </form>
    <p v-if="error" role="alert" :class="ERROR">{{ error }} <button v-if="!state" type="button" class="underline" @click="load">Tentar de novo</button></p>
    <p class="m-0 text-xs text-fg-subtle"><a href="https://github.com/vateiixeira/claudio-maestro#comentários-no-pr" target="_blank" rel="noopener noreferrer" class="text-info-soft hover:text-fg">Como configurar os comentários no PR</a></p>
  </section>
</template>
