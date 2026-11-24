<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { errorMessage, getAppState, listProviders, putAppState } from '../../api/http'
import { ALL_EFFORTS, ALL_MODES, CODEX_EFFORTS, EFFORT_LABELS, KIMI_EFFORTS, MODE_LABELS } from '../../sessionOptions'
import { useModelsStore } from '../../stores/models'
import { useLayoutStore } from '../../stores/layout'
import type { Effort, PermissionMode } from '../../types/api'
import BypassConfirmDialog from '../session/BypassConfirmDialog.vue'
import OptionMenu, { type MenuOption } from '../session/OptionMenu.vue'
import ClaudeProfilePreferences from './ClaudeProfilePreferences.vue'
import CodexPreferences from './CodexPreferences.vue'

// Menu value of "Padrão"; it must not collide with a real option (the "default" mode, the SDK's "default" model).
const INHERIT = 'inherit-default'

const models = useModelsStore()
const layout = useLayoutStore()
void models.ensure()

const loading = ref(true)
const loadError = ref<string | null>(null)
// Defaults for new conversations; `null` is "Padrão" (the CLI decides).
const newModel = ref<string | null>(null)
const newEffort = ref<Effort | null>(null)
const newMode = ref<PermissionMode | null>(null)
// Kimi Code as a provider of new conversations; `kimiInstalled` is null while unknown.
const kimiEnabled = ref(false)
const kimiInstalled = ref<boolean | null>(null)
// Defaults for new Kimi conversations; `null` is "Padrão" (the Kimi CLI decides).
const kimiNewModel = ref<string | null>(null)
const kimiNewEffort = ref<Effort | null>(null)
const codexEnabled = ref(false)
const codexInstalled = ref<boolean | null>(null)
const codexNewModel = ref<string | null>(null)
const codexNewEffort = ref<Effort | null>(null)
watch(kimiEnabled, (enabled) => { if (enabled) void models.ensureKimi() })
// "Sem perguntas" runs every tool without asking, so choosing it opens a confirmation first.
const confirmingBypass = ref(false)
function selectMode(value: string) {
  if (value === 'bypassPermissions') {
    confirmingBypass.value = true
    return
  }
  newMode.value = value === INHERIT ? null : (value as PermissionMode)
}
function confirmBypass() {
  confirmingBypass.value = false
  newMode.value = 'bypassPermissions'
}
const saving = ref(false)
const saved = ref(false)
const error = ref<string | null>(null)

const modelOptions = computed<MenuOption[]>(() => [
  { value: INHERIT, label: 'Padrão' },
  ...models.models.map((m) => ({ value: m.value, label: m.displayName, description: m.description })),
])
const modelText = computed(() => models.models.find((m) => m.value === newModel.value)?.displayName ?? newModel.value ?? 'Padrão')
const effortOptions: MenuOption[] = [
  { value: INHERIT, label: 'Padrão' },
  ...ALL_EFFORTS.map((e) => ({ value: e, label: EFFORT_LABELS[e] })),
]
const modeOptions: MenuOption[] = [
  { value: INHERIT, label: 'Padrão da conta' },
  ...ALL_MODES.map((m) => ({ value: m, label: MODE_LABELS[m] })),
]
const kimiModelOptions = computed<MenuOption[]>(() => [
  { value: INHERIT, label: 'Padrão' },
  ...models.kimiModels.map((m) => ({ value: m.value, label: m.displayName, description: m.description })),
])
const kimiModelText = computed(() => models.kimiModels.find((m) => m.value === kimiNewModel.value)?.displayName ?? kimiNewModel.value ?? 'Padrão')
const kimiEffortOptions: MenuOption[] = [
  { value: INHERIT, label: 'Padrão' },
  ...KIMI_EFFORTS.map((e) => ({ value: e, label: EFFORT_LABELS[e] })),
]

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
    newModel.value = typeof prefs.new_session_model === 'string' && prefs.new_session_model.trim() !== '' ? prefs.new_session_model : null
    newEffort.value = ALL_EFFORTS.find((e) => e === prefs.new_session_effort) ?? null
    newMode.value = ALL_MODES.find((m) => m === prefs.new_session_mode) ?? null
    kimiEnabled.value = prefs.kimi_enabled === true
    kimiNewModel.value = typeof prefs.kimi_new_session_model === 'string' && prefs.kimi_new_session_model.trim() !== '' ? prefs.kimi_new_session_model : null
    kimiNewEffort.value = KIMI_EFFORTS.find((e) => e === prefs.kimi_new_session_effort) ?? null
    codexEnabled.value = prefs.codex_enabled === true
    codexNewModel.value = typeof prefs.codex_new_session_model === 'string' && prefs.codex_new_session_model.trim() !== '' ? prefs.codex_new_session_model : null
    codexNewEffort.value = CODEX_EFFORTS.find((e) => e === prefs.codex_new_session_effort) ?? null
    saved.value = false
    error.value = null
  } catch (e) {
    loadError.value = errorMessage(e)
  } finally {
    loading.value = false
  }
  listProviders()
    .then((list) => {
      const entries = Array.isArray(list) ? list : []
      kimiInstalled.value = entries.find((p) => p.id === 'kimi')?.available ?? null
      codexInstalled.value = entries.find((p) => p.id === 'codex')?.available ?? null
    })
    .catch(() => {}) // without the status the help text just does not say it
}

// Any edit takes the confirmation away.
watch([newModel, newEffort, newMode, kimiEnabled, kimiNewModel, kimiNewEffort, codexEnabled, codexNewModel, codexNewEffort], () => { saved.value = false })

async function save(): Promise<void> {
  if (!ready.value || saving.value) return
  error.value = null
  saved.value = false
  saving.value = true
  try {
    // The whole object is saved: read it again so keys changed elsewhere are kept.
    const prefs = preferencesOf(await getAppState())
    prefs.new_session_model = newModel.value
    prefs.new_session_effort = newEffort.value
    prefs.new_session_mode = newMode.value
    prefs.kimi_enabled = kimiEnabled.value
    prefs.kimi_new_session_model = kimiNewModel.value
    prefs.kimi_new_session_effort = kimiNewEffort.value
    prefs.codex_enabled = codexEnabled.value
    prefs.codex_new_session_model = codexNewModel.value
    prefs.codex_new_session_effort = codexNewEffort.value
    await putAppState('preferences', prefs)
    layout.codexEnabled = prefs.codex_enabled === true
    await nextTick() // let the edit watcher run before confirming
    saved.value = true
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <form class="flex flex-col" aria-label="Preferências de conversas" @submit.prevent="save">
    <div v-if="loadError" class="flex flex-col items-start gap-3 px-7 py-6">
      <p role="alert" class="m-0 w-full rounded-lg border border-diff-del-fg/40 bg-diff-del-bg px-3.5 py-2.5 text-sm text-diff-del-fg">
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
      <fieldset class="m-0 flex min-w-0 flex-col gap-2 border-0 p-0" :disabled="!ready" aria-describedby="pref-new-help">
        <legend class="mb-2 p-0 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Conversas novas</legend>
        <div class="flex flex-wrap items-center gap-2">
          <OptionMenu
            data-test="pref-new-model"
            name="Modelo padrão"
            :text="modelText"
            :options="modelOptions"
            :selected="newModel ?? INHERIT"
            :disabled="!ready"
            @select="(v) => (newModel = v === INHERIT ? null : v)"
          />
          <OptionMenu
            data-test="pref-new-effort"
            name="Raciocínio padrão"
            :text="`Raciocínio ${newEffort ? EFFORT_LABELS[newEffort] : 'padrão'}`"
            :options="effortOptions"
            :selected="newEffort ?? INHERIT"
            :disabled="!ready"
            @select="(v) => (newEffort = v === INHERIT ? null : (v as Effort))"
          />
          <OptionMenu
            data-test="pref-new-mode"
            name="Modo padrão"
            :text="newMode ? MODE_LABELS[newMode] : 'Modo padrão'"
            :options="modeOptions"
            :selected="newMode ?? INHERIT"
            :highlight="newMode === 'bypassPermissions'"
            :disabled="!ready"
            @select="selectMode"
          />
        </div>
        <p id="pref-new-help" class="m-0 text-xs text-fg-muted">
          Valem para novas conversas com o Claude. "Padrão" segue o modelo e o raciocínio do Claude e o modo do seu
          <span class="font-mono">settings.json</span>. Dá para mudar na própria conversa. "Sem perguntas" pede confirmação ao escolher.
        </p>
      </fieldset>

      <fieldset class="m-0 flex min-w-0 flex-col gap-2 border-0 p-0" :disabled="!ready" aria-describedby="pref-kimi-help">
        <legend class="mb-2 p-0 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Agentes</legend>
        <label class="flex cursor-pointer items-center gap-2.5 text-sm text-fg has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-fg-muted">
          <input
            v-model="kimiEnabled"
            type="checkbox"
            data-test="pref-kimi"
            class="size-4 accent-primary"
            :disabled="!ready"
          />
          Kimi Code
        </label>
        <p id="pref-kimi-help" class="m-0 text-xs text-fg-muted">
          Oferece o Kimi como agente para novas conversas.
          Precisa do <span class="font-mono">kimi</span> instalado e logado nesta máquina.
          <template v-if="kimiInstalled === true">O comando <span class="font-mono">kimi</span> foi encontrado.</template>
          <template v-else-if="kimiInstalled === false">O comando <span class="font-mono">kimi</span> não foi encontrado nesta máquina.</template>
        </p>
        <div v-if="kimiEnabled" class="mt-1 flex flex-col gap-2">
          <span class="font-mono text-xs tracking-[0.08em] text-fg-subtle uppercase">Conversas novas do Kimi</span>
          <div class="flex flex-wrap items-center gap-2">
            <OptionMenu
              data-test="pref-kimi-model"
              name="Modelo padrão do Kimi"
              :text="kimiModelText"
              :options="kimiModelOptions"
              :selected="kimiNewModel ?? INHERIT"
              :disabled="!ready"
              @select="(v) => (kimiNewModel = v === INHERIT ? null : v)"
            />
            <OptionMenu
              data-test="pref-kimi-effort"
              name="Raciocínio padrão do Kimi"
              :text="`Raciocínio ${kimiNewEffort ? EFFORT_LABELS[kimiNewEffort] : 'padrão'}`"
              :options="kimiEffortOptions"
              :selected="kimiNewEffort ?? INHERIT"
              :disabled="!ready"
              @select="(v) => (kimiNewEffort = v === INHERIT ? null : (v as Effort))"
            />
          </div>
          <p class="m-0 text-xs text-fg-muted">
            Valem para toda conversa nova do Kimi Code. "Padrão" deixa a decisão com o Kimi.
            Dá para mudar na própria conversa.
          </p>
        </div>
        <CodexPreferences
          v-model:enabled="codexEnabled"
          v-model:model="codexNewModel"
          v-model:effort="codexNewEffort"
          :disabled="!ready"
          :installed="codexInstalled"
        />
      </fieldset>

      <ClaudeProfilePreferences />
    </div>

    <p
      v-if="error"
      role="alert"
      class="mx-7 mb-4 rounded-lg border border-diff-del-fg/40 bg-diff-del-bg px-3.5 py-2.5 text-sm text-diff-del-fg"
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

    <BypassConfirmDialog v-if="confirmingBypass" @cancel="confirmingBypass = false" @confirm="confirmBypass" />
  </form>
</template>
