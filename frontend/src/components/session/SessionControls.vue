<script setup lang="ts">
import { computed, ref } from 'vue'
import { errorMessage, updateSession } from '../../api/http'
import { useConversationStore } from '../../stores/conversation'
import { formatTokens } from '../../format'
import { useModelsStore } from '../../stores/models'
import { useSessionsStore } from '../../stores/sessions'
import type { Effort, PermissionMode, SessionUpdate } from '../../types/api'
import { ALL_EFFORTS, EFFORT_LABELS, MODE_LABELS, modeLabel } from '../../sessionOptions'
import BypassConfirmDialog from './BypassConfirmDialog.vue'
import ClaudeCliFooter from './ClaudeCliFooter.vue'
import OptionMenu, { type MenuOption } from './OptionMenu.vue'

const props = defineProps<{ sessionId: string }>()

const conversations = useConversationStore()
const modelsStore = useModelsStore()
void modelsStore.ensure()

const options = computed(() => conversations.get(props.sessionId)?.options)

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
// One line each, only what the app and the SDK confirm (see the spec, 7.1, and the permission cards).
const MODE_DESCRIPTIONS: Record<PermissionMode, string> = {
  default: 'Pergunta antes de editar arquivos ou rodar comandos.',
  acceptEdits: 'Aplica edições de arquivos sem perguntar; o resto ainda pede.',
  plan: 'Só planeja: propõe um plano e espera sua aprovação.',
  bypassPermissions: 'Roda tudo sem pedir permissão. Pede confirmação ao ativar.',
  auto: 'Modo automático do Claude. Nem todo modelo aceita.',
  dontAsk: 'Não pergunta: só roda o que já está pré-aprovado.',
}
const modeOptions: MenuOption[] = (Object.keys(MODE_LABELS) as PermissionMode[]).map((m) => ({
  value: m,
  label: MODE_LABELS[m],
  description: MODE_DESCRIPTIONS[m],
}))

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
function selectMode(value: string) {
  if (value === 'bypassPermissions') {
    confirming.value = true
    return
  }
  void apply({ permission_mode: value as PermissionMode })
}
function confirmBypass() {
  confirming.value = false
  void apply({ permission_mode: 'bypassPermissions', confirm_bypass: true })
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
    >
      <template #footer><ClaudeCliFooter /></template>
    </OptionMenu>
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
      :name="`Permissões: ${modeLabel(mode).toLowerCase()}`"
      prefix="Permissões:"
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
      :class="contextWarn ? 'text-secondary' : 'text-fg-subtle'"
    >Contexto {{ contextPercent }}%</span>
    <span v-if="context && contextWarn" data-test="context-usage-sr" class="sr-only">Contexto {{ contextPercent }}%, {{ contextTitle }}</span>
    <span v-if="options.effort_pending" data-test="effort-pending" class="text-xs text-fg-subtle">vale a partir do próximo turno</span>
    <p v-if="error" role="alert" class="m-0 w-full text-sm text-diff-del-fg">{{ error }}</p>

    <BypassConfirmDialog v-if="confirming" @cancel="confirming = false" @confirm="confirmBypass" />
  </div>
</template>
