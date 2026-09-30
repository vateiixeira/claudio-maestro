<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { errorMessage, getAppState, putAppState } from '../../api/http'
import { editorCommandProblem, formatEditorCommand, parseEditorCommand } from '../../preferences'
import { loadEverything } from '../../stores/realtime'
import { DEFAULT_FINISHED_AFTER_DAYS, useLayoutStore } from '../../stores/layout'

const MIN_DAYS = 1
const MAX_DAYS = 365
const DEFAULT_EDITOR = 'code'

const layout = useLayoutStore()

const loading = ref(true)
const loadError = ref<string | null>(null)
const editorText = ref('')
const daysText = ref(String(layout.finishedAfterDays))
const saving = ref(false)
const saved = ref(false)
const error = ref<string | null>(null)

const ready = computed(() => !loading.value && loadError.value === null)

function preferencesOf(state: unknown): Record<string, unknown> {
  const value = (state as Record<string, unknown> | null | undefined)?.preferences
  return value && typeof value === 'object' && !Array.isArray(value) ? { ...(value as Record<string, unknown>) } : {}
}

async function load(): Promise<void> {
  loading.value = true
  loadError.value = null
  try {
    const prefs = preferencesOf(await getAppState())
    const command = prefs.editor_command
    editorText.value = Array.isArray(command) && command.every((p) => typeof p === 'string') ? formatEditorCommand(command) : ''
    const days = prefs.finished_after_days
    daysText.value = String(typeof days === 'number' && Number.isInteger(days) && days > 0 ? days : DEFAULT_FINISHED_AFTER_DAYS)
    saved.value = false
    error.value = null
  } catch (e) {
    loadError.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

// Any edit takes the confirmation away.
watch([editorText, daysText], () => { saved.value = false })

async function save(): Promise<void> {
  if (!ready.value || saving.value) return
  error.value = null
  saved.value = false
  const raw = String(daysText.value).trim() // a number input gives a number
  const days = Number(raw)
  if (!/^\d+$/.test(raw) || days < MIN_DAYS || days > MAX_DAYS) {
    error.value = `Informe um número inteiro de dias entre ${MIN_DAYS} e ${MAX_DAYS}.`
    return
  }
  let command: string[]
  try {
    command = parseEditorCommand(editorText.value)
  } catch (e) {
    error.value = errorMessage(e)
    return
  }
  const problem = editorCommandProblem(command)
  if (problem) {
    error.value = problem
    return
  }
  saving.value = true
  try {
    // The whole object is saved: read it again so keys changed elsewhere are kept.
    const prefs = preferencesOf(await getAppState())
    const daysChanged = prefs.finished_after_days !== days
    prefs.finished_after_days = days
    if (command.length > 0) prefs.editor_command = command
    else delete prefs.editor_command
    await putAppState('preferences', prefs)
    layout.finishedAfterDays = days
    daysText.value = String(days)
    editorText.value = formatEditorCommand(command)
    await nextTick() // let the edit watcher run before confirming
    saved.value = true
    // Hidden counts and finished sessions depend on the number of days.
    if (daysChanged) loadEverything().catch(() => {})
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <form class="flex flex-col" aria-label="Preferências gerais" @submit.prevent="save">
    <div v-if="loadError" class="flex flex-col items-start gap-3 px-7 py-6">
      <p role="alert" class="m-0 w-full rounded-lg border border-secondary/40 bg-card px-3.5 py-2.5 text-sm text-secondary-soft">
        Não foi possível ler as preferências. {{ loadError }}
      </p>
      <button
        type="button"
        data-test="retry"
        class="h-11 rounded-lg border border-line-strong px-4 font-medium text-fg hover:bg-card"
        @click="load"
      >
        Tentar de novo
      </button>
    </div>

    <div class="flex flex-col gap-7 px-7 py-6" :aria-busy="loading">
      <div class="flex flex-col gap-2">
        <label for="pref-editor" class="font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Comando do editor</label>
        <input
          id="pref-editor"
          v-model="editorText"
          type="text"
          autocomplete="off"
          spellcheck="false"
          :placeholder="DEFAULT_EDITOR"
          :disabled="!ready"
          aria-describedby="pref-editor-help"
          class="h-11 rounded-lg border border-line-strong bg-bg px-3.5 font-mono text-sm text-fg outline-none placeholder:text-fg-muted focus:border-primary disabled:opacity-40"
        />
        <p id="pref-editor-help" data-test="editor-help" class="m-0 text-xs text-fg-muted">
          Usado por "Abrir no editor". O caminho do arquivo ou da pasta é adicionado ao final do comando, como em
          <span class="font-mono">code --reuse-window /caminho</span>; não escreva o caminho aqui.
          O comando roda direto, sem shell: use aspas para partes com espaço. Vazio usa
          <span class="font-mono">{{ DEFAULT_EDITOR }}</span>.
        </p>
      </div>

      <div class="flex flex-col gap-2">
        <label for="pref-days" class="font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Dias para ocultar sessões</label>
        <input
          id="pref-days"
          v-model="daysText"
          type="number"
          inputmode="numeric"
          :min="MIN_DAYS"
          :max="MAX_DAYS"
          step="1"
          :disabled="!ready"
          aria-describedby="pref-days-help"
          class="h-11 w-32 rounded-lg border border-line-strong bg-bg px-3.5 text-sm text-fg outline-none focus:border-primary disabled:opacity-40"
        />
        <p id="pref-days-help" class="m-0 text-xs text-fg-muted">
          Sessões paradas há mais dias que isso saem do menu e ficam em Finalizadas, na tela do projeto. De {{ MIN_DAYS }} a {{ MAX_DAYS }}.
        </p>
      </div>
    </div>

    <p
      v-if="error"
      role="alert"
      class="mx-7 mb-4 rounded-lg border border-secondary/40 bg-card px-3.5 py-2.5 text-sm text-secondary-soft"
    >
      {{ error }}
    </p>

    <footer class="flex items-center justify-end gap-3 border-t border-line px-7 pt-4 pb-5">
      <p v-if="saved" data-test="saved" role="status" class="m-0 flex items-center gap-1.5 text-sm text-primary-soft">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M5 12l5 5 9-10" />
        </svg>
        Preferências salvas
      </p>
      <button
        type="submit"
        data-test="save"
        class="h-11 rounded-lg bg-primary px-[18px] font-semibold text-primary-fg hover:bg-primary-soft disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-primary"
        :disabled="!ready || saving"
      >
        {{ saving ? 'Salvando…' : 'Salvar' }}
      </button>
    </footer>
  </form>
</template>
