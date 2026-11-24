<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { errorMessage, updateSession } from '../../api/http'
import { useConversationStore } from '../../stores/conversation'
import { useCodexCliStore } from '../../stores/codexCli'
import { useModelsStore } from '../../stores/models'
import { useSessionsStore } from '../../stores/sessions'
import type { Effort, PermissionMode, RemoteControlState, SessionUpdate } from '../../types/api'
import { shortModelLabel } from '../../modelLabel'
import { ALL_EFFORTS, codexDefaultModel, codexEffortLevels, EFFORT_LABELS, MODE_LABELS, modeLabel } from '../../sessionOptions'
import BypassConfirmDialog from './BypassConfirmDialog.vue'
import ClaudeCliFooter from './ClaudeCliFooter.vue'
import CodexCliFooter from './CodexCliFooter.vue'
import ContextIndicator from './ContextIndicator.vue'
import OptionMenu, { type MenuOption } from './OptionMenu.vue'
import RemoteControlChip from './RemoteControlChip.vue'

const props = defineProps<{ sessionId: string }>()

const conversations = useConversationStore()
const modelsStore = useModelsStore()
const codexCli = useCodexCliStore()
// The session summary is refreshed by events; the snapshot only holds what it had at load.
const sessionsStore = useSessionsStore()

const options = computed(() => conversations.get(props.sessionId)?.options)
// The provider never changes during the session; the summary knows it.
const provider = computed(() => sessionsStore.find(props.sessionId)?.provider ?? 'claude')
const providerModels = computed(() => modelsStore.modelsFor(provider.value))
watch(provider, (value) => {
  void modelsStore.ensureFor(value)
  if (value === 'codex') void codexCli.load()
}, { immediate: true })

const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

const modelValue = computed(() => options.value?.model ?? 'default')
const currentModel = computed(() => {
  const chosen = providerModels.value.find((model) => model.value === modelValue.value)
  if (provider.value !== 'codex' || modelValue.value !== 'default') return chosen
  const resolved = options.value?.model_resolved ?? codexCli.info?.default_model
  return codexDefaultModel(providerModels.value, resolved)
})
const modelText = computed(() => currentModel.value?.displayName ?? options.value?.model ?? (provider.value === 'codex' ? options.value?.model_resolved : null) ?? 'Padrão')
// The button shows the short name; when that drops a suffix, the tooltip keeps the full one.
const modelTitle = computed(() => {
  const parts = shortModelLabel(modelText.value) !== modelText.value ? [modelText.value] : []
  if (options.value?.model_resolved) parts.push(`Em uso: ${options.value.model_resolved}`)
  return parts.length ? parts.join(' · ') : undefined
})
const modelOptions = computed<MenuOption[]>(() => [
  ...(provider.value === 'codex' ? [{ value: 'default', label: 'Padrão do Codex' }] : []),
  ...providerModels.value.filter((model) => provider.value !== 'codex' || model.value !== 'default')
    .map((m) => ({ value: m.value, label: m.displayName, description: m.description })),
])

// Levels of the chosen model; every level while the model list is unknown.
const effortLevels = computed<Effort[]>(() => {
  const model = currentModel.value
  if (provider.value === 'codex') return codexEffortLevels(model)
  if (!model) return providerModels.value.length ? [] : ALL_EFFORTS
  if (!model.supportsEffort) return []
  return model.supportedEffortLevels?.length ? model.supportedEffortLevels : ALL_EFFORTS
})
const effortText = computed(() => {
  const effort = options.value?.effort
  if (effort) return `Raciocínio ${EFFORT_LABELS[effort]}`
  const fallback = provider.value === 'codex'
    ? (modelValue.value === 'default' ? (codexCli.info?.default_effort ?? currentModel.value?.defaultEffort) : currentModel.value?.defaultEffort)
    : null
  return fallback ? `Raciocínio padrão · ${EFFORT_LABELS[fallback]}` : 'Raciocínio padrão'
})
const effortOptions = computed<MenuOption[]>(() => [
  ...(provider.value === 'codex' ? [{ value: 'default', label: 'Padrão' }] : []),
  ...effortLevels.value.map((e) => ({ value: e, label: capitalize(EFFORT_LABELS[e]) })),
])

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
// No Kimi os modos do app viram os modos dele (default, plan, auto, yolo).
const KIMI_MODE_DESCRIPTIONS: Partial<Record<PermissionMode, string>> = {
  acceptEdits: 'Aprova operações seguras automaticamente (modo Auto do Kimi).',
  auto: 'Aprova operações seguras automaticamente (modo Auto do Kimi).',
  dontAsk: 'Aprova tudo sem perguntar (modo YOLO do Kimi).',
  bypassPermissions: 'Aprova tudo sem perguntar (modo YOLO do Kimi). Pede confirmação ao ativar.',
}
const CODEX_MODE_DESCRIPTIONS: Record<PermissionMode, string> = {
  default: 'Começa em modo de leitura e pede permissão para ações que exigem aprovação.',
  acceptEdits: 'Permite edições na pasta de trabalho e pede aprovação para sair dela.',
  plan: 'Usa o modo de planejamento do Codex para explorar e propor um plano.',
  bypassPermissions: 'Executa com acesso completo. Pede confirmação ao ativar.',
  auto: 'Permite edições na pasta de trabalho e usa a revisão automática do Codex.',
  dontAsk: 'Permite ações dentro do isolamento da pasta de trabalho, sem pedir acesso adicional.',
}
const modeDescriptions = { claude: MODE_DESCRIPTIONS, kimi: { ...MODE_DESCRIPTIONS, ...KIMI_MODE_DESCRIPTIONS }, codex: CODEX_MODE_DESCRIPTIONS }
const modeOptions = computed<MenuOption[]>(() => (Object.keys(MODE_LABELS) as PermissionMode[]).map((m) => ({
  value: m,
  label: MODE_LABELS[m],
  description: modeDescriptions[provider.value][m],
})))

// An agent session stays in the default mode: the backend refuses every change (422).
const isAgentSession = computed(() => sessionsStore.find(props.sessionId)?.agent_id != null)
const AGENT_MODE_HINT = 'Sessões de agente ficam no modo padrão; as ações para fora seguem a autonomia do agente.'
const context = computed(() => {
  // The list can carry `null` (no connected client); the snapshot then holds the value from the history.
  return sessionsStore.find(props.sessionId)?.context ?? conversations.get(props.sessionId)?.context ?? null
})

// The mark on with nothing holding it (`off`) is shown as connecting: the backend reconnects by itself.
const remoteState = computed<RemoteControlState>(() => {
  const o = options.value
  if (!o?.remote_control) return 'off'
  return o.remote_control_state === 'off' ? 'connecting' : o.remote_control_state
})
// A finished session cannot be reconnected; the backend answers 409 until it is reopened.
const sessionFinished = computed(() => sessionsStore.find(props.sessionId)?.finished === true)

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

function selectModel(value: string) {
  const changes: SessionUpdate = { model: value }
  const effort = options.value?.effort
  if (provider.value === 'codex' && effort) {
    const selected = value === 'default'
      ? codexDefaultModel(providerModels.value, codexCli.info?.default_model)
      : providerModels.value.find((model) => model.value === value)
    if (selected && !codexEffortLevels(selected).includes(effort)) changes.effort = 'default'
  }
  void apply(changes)
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
  <div v-if="options" class="flex min-w-0 grow flex-wrap items-center gap-0.5">
    <RemoteControlChip
      v-if="provider === 'claude'"
      :state="remoteState"
      :url="options.remote_control_url"
      :error="options.remote_control_error"
      :disabled="saving || sessionFinished"
      @toggle="(enabled) => apply({ remote_control: enabled })"
    />
    <OptionMenu
      :name="`Modelo: ${modelText}`"
      :text="shortModelLabel(modelText)"
      :title="modelTitle"
      :options="modelOptions"
      :selected="modelValue"
      :disabled="saving"
      @select="selectModel"
    >
      <template v-if="provider === 'claude'" #footer><ClaudeCliFooter /></template>
      <template v-else-if="provider === 'codex'" #footer><CodexCliFooter /></template>
    </OptionMenu>
    <OptionMenu
      v-if="effortLevels.length || (provider === 'codex' && options.effort)"
      :name="`Raciocínio: ${options.effort ? EFFORT_LABELS[options.effort] : 'padrão'}`"
      :text="effortText"
      :options="effortOptions"
      :selected="options.effort ?? (provider === 'codex' ? 'default' : null)"
      :disabled="saving"
      @select="(v) => apply({ effort: v as Effort | 'default' })"
    />
    <OptionMenu
      :name="`Permissões: ${modeLabel(mode).toLowerCase()}`"
      :text="modeLabel(mode)"
      :options="modeOptions"
      :selected="mode"
      :highlight="mode === 'bypassPermissions'"
      :title="isAgentSession ? AGENT_MODE_HINT : undefined"
      :disabled="saving || isAgentSession"
      @select="selectMode"
    />
    <ContextIndicator v-if="context" :session-id="sessionId" :context="context" class="ml-auto" />
    <span v-if="options.effort_pending" data-test="effort-pending" class="text-xs text-fg-subtle">vale a partir do próximo turno</span>
    <p v-if="error" role="alert" class="m-0 w-full text-sm text-diff-del-fg">{{ error }}</p>

    <BypassConfirmDialog v-if="confirming" @cancel="confirming = false" @confirm="confirmBypass" />
  </div>
</template>
