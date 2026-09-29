<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { errorMessage, updateSession } from '../../api/http'
import { useConversationStore } from '../../stores/conversation'
import { formatTokens } from '../../format'
import { useModelsStore } from '../../stores/models'
import { useSessionsStore } from '../../stores/sessions'
import type { Effort, PermissionMode, SessionUpdate } from '../../types/api'
import OptionMenu, { type MenuOption } from './OptionMenu.vue'

const props = defineProps<{ sessionId: string }>()

const conversations = useConversationStore()
const modelsStore = useModelsStore()
void modelsStore.ensure()

const options = computed(() => conversations.get(props.sessionId)?.options)

const EFFORT_LABELS: Record<Effort, string> = {
  low: 'baixo',
  medium: 'médio',
  high: 'alto',
  xhigh: 'muito alto',
  max: 'máximo',
}
const ALL_EFFORTS = Object.keys(EFFORT_LABELS) as Effort[]
const MODE_LABELS: Record<PermissionMode, string> = {
  default: 'Pede permissão',
  acceptEdits: 'Aceita edições',
  plan: 'Planejamento',
  bypassPermissions: 'Sem perguntas',
  auto: 'Automático',
  dontAsk: 'Só o pré-aprovado',
}
// A mode the CLI knows but the app does not shows its raw value.
const modeLabel = (m: string) => MODE_LABELS[m as PermissionMode] ?? m

const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

const modelValue = computed(() => options.value?.model ?? 'default')
const currentModel = computed(() => modelsStore.models.find((m) => m.value === modelValue.value))
const modelText = computed(() => currentModel.value?.displayName ?? options.value?.model ?? 'Padrão')
const modelTitle = computed(() => (options.value?.model_resolved ? `Em uso: ${options.value.model_resolved}` : undefined))
const modelOptions = computed<MenuOption[]>(() =>
  modelsStore.models.map((m) => ({ value: m.value, label: m.displayName, description: m.description })),
)

// Levels of the chosen model; every level while the model list is unknown.
const effortLevels = computed<Effort[]>(() => {
  const model = currentModel.value
  if (!model) return modelsStore.models.length ? [] : ALL_EFFORTS
  if (!model.supportsEffort) return []
  return model.supportedEffortLevels?.length ? model.supportedEffortLevels : ALL_EFFORTS
})
const effortText = computed(() => {
  const effort = options.value?.effort
  return `Raciocínio ${effort ? EFFORT_LABELS[effort] : 'padrão'}`
})
const effortOptions = computed<MenuOption[]>(() =>
  effortLevels.value.map((e) => ({ value: e, label: capitalize(EFFORT_LABELS[e]) })),
)

const mode = computed<string>(() => options.value?.permission_mode ?? 'default')
const modeOptions: MenuOption[] = (Object.keys(MODE_LABELS) as PermissionMode[]).map((m) => ({ value: m, label: MODE_LABELS[m] }))

// The session summary is refreshed by events; the snapshot only holds what it had at load.
const sessionsStore = useSessionsStore()
const context = computed(() => {
  // The list can carry `null` (no connected client); the snapshot then holds the value from the history.
  return sessionsStore.find(props.sessionId)?.context ?? conversations.get(props.sessionId)?.context ?? null
})
const contextPercent = computed(() => (context.value ? Math.round(context.value.percent) : 0))
const contextTitle = computed(() =>
  context.value
    // "1 milhão de tokens", but "200 mil tokens".
    ? `${formatTokens(context.value.used_tokens)} de ${formatTokens(context.value.max_tokens)}${context.value.max_tokens >= 1_000_000 ? ' de' : ''} tokens`
    : undefined,
)
const contextWarn = computed(() => contextPercent.value >= 80)

const error = ref<string | null>(null)
const saving = ref(false)
async function apply(changes: SessionUpdate) {
  saving.value = true
  error.value = null
  // A `session.options` newer than this request wins over its response.
  const stamp = conversations.optionsStamp(props.sessionId)
  try {
    const session = await updateSession(props.sessionId, changes)
    if (session && conversations.optionsStamp(props.sessionId) === stamp) {
      conversations.setOptions(props.sessionId, session)
    }
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    saving.value = false
  }
}

// "Sem perguntas" runs every tool without asking, so it needs an explicit confirmation.
const confirming = ref(false)
const confirmButton = ref<HTMLButtonElement | null>(null)
const cancelButton = ref<HTMLButtonElement | null>(null)
let returnFocusTo: HTMLElement | null = null
async function selectMode(value: string) {
  if (value === 'bypassPermissions') {
    returnFocusTo = document.activeElement as HTMLElement | null
    confirming.value = true
    await nextTick()
    confirmButton.value?.focus()
    return
  }
  void apply({ permission_mode: value as PermissionMode })
}
async function closeDialog() {
  confirming.value = false
  const target = returnFocusTo
  returnFocusTo = null
  await nextTick()
  target?.focus()
}
function cancelBypass() {
  void closeDialog()
}
function confirmBypass() {
  void closeDialog()
  void apply({ permission_mode: 'bypassPermissions', confirm_bypass: true })
}
// Keeps Tab and Shift+Tab between the two buttons while the dialog is open.
function onDialogKey(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    cancelBypass()
  } else if (event.key === 'Tab') {
    event.preventDefault()
    // Two buttons: either direction goes to the other one.
    const onCancel = document.activeElement === cancelButton.value
    ;(onCancel ? confirmButton : cancelButton).value?.focus()
  }
}
</script>

<template>
  <div v-if="options" class="flex flex-wrap items-center gap-2">
    <OptionMenu
      :name="`Modelo: ${modelText}`"
      :text="modelText"
      :title="modelTitle"
      :options="modelOptions"
      :selected="modelValue"
      :disabled="saving"
      @select="(v) => apply({ model: v })"
    />
    <OptionMenu
      v-if="effortLevels.length"
      :name="`Raciocínio: ${options.effort ? EFFORT_LABELS[options.effort] : 'padrão'}`"
      :text="effortText"
      :options="effortOptions"
      :selected="options.effort"
      :disabled="saving"
      @select="(v) => apply({ effort: v as Effort })"
    />
    <OptionMenu
      :name="`Modo: ${modeLabel(mode).toLowerCase()}`"
      :text="modeLabel(mode)"
      :options="modeOptions"
      :selected="mode"
      :highlight="mode === 'bypassPermissions'"
      :disabled="saving"
      @select="selectMode"
    />
    <span
      v-if="context && contextWarn"
      data-test="context-usage"
      :title="contextTitle"
      aria-hidden="true"
      class="font-mono text-xs"
      :class="contextWarn ? 'text-secondary' : 'text-fg-muted'"
    >Contexto {{ contextPercent }}%</span>
    <span v-if="context && contextWarn" data-test="context-usage-sr" class="sr-only">Contexto {{ contextPercent }}%, {{ contextTitle }}</span>
    <span v-if="options.effort_pending" data-test="effort-pending" class="text-xs text-fg-muted">vale a partir do próximo turno</span>
    <p v-if="error" role="alert" class="m-0 w-full text-sm text-diff-del-fg">{{ error }}</p>

    <div
      v-if="confirming"
      data-test="bypass-overlay"
      class="fixed inset-0 z-40 flex items-center justify-center bg-bg/70 p-4"
      @click.self="cancelBypass"
      @keydown="onDialogKey"
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="bypass-title"
        aria-describedby="bypass-text"
        class="flex max-w-md flex-col gap-3 rounded-lg border border-secondary/50 bg-elevated p-5"
      >
        <h3 id="bypass-title" class="m-0 text-base font-semibold text-secondary">Ativar "Sem perguntas"?</h3>
        <p id="bypass-text" class="m-0 text-sm text-fg">
          O Claude vai editar arquivos e rodar comandos nesta máquina sem pedir sua permissão.
          Um erro dele pode apagar dados ou alterar coisas fora do projeto. Use só quando confiar na tarefa.
        </p>
        <div class="flex justify-end gap-2">
          <button
            type="button"
            ref="cancelButton"
            data-test="bypass-cancel"
            class="h-9 cursor-pointer rounded-md border border-line-strong bg-transparent px-3 text-sm text-fg hover:bg-card"
            @click="cancelBypass"
          >Cancelar</button>
          <button
            ref="confirmButton"
            type="button"
            data-test="bypass-confirm"
            class="h-9 cursor-pointer rounded-md border-none bg-secondary px-3 text-sm font-semibold text-secondary-fg"
            @click="confirmBypass"
          >Ativar sem perguntas</button>
        </div>
      </div>
    </div>
  </div>
</template>
