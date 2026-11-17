<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import AgentStateIcon from '../AgentStateIcon.vue'
import ConfirmDialog from '../../ConfirmDialog.vue'
import IconAlert from '../../icons/IconAlert.vue'
import MoreMenu, { type MoreMenuItem } from '../../ui/MoreMenu.vue'
import ToggleSwitch from '../../ui/ToggleSwitch.vue'
import { duplicateAgent, errorMessage, updateAgent, wakeAgent } from '../../../api/http'
import { formatModelName } from '../../../format'
import { SLUG_MAX_LENGTH, agentState, slugify } from '../../../org'
import { useOrgStore } from '../../../stores/org'
import { useProjectsStore } from '../../../stores/projects'
import { useSessionsStore } from '../../../stores/sessions'
import { nextSlot, slotLabel } from '../routines/schedule'
import { BTN, ERROR, FIELD } from '../styles'

// The top of the agent panel: who it is (name, model, boss), the switch, "run now" and the "more actions" menu
// (run with an instruction, change the boss, copy to another project, delete). A switched-off agent gets a
// warning that says what stops running, with the button to turn it back on.
const props = defineProps<{ agentId: number }>()
const emit = defineEmits<{ deleted: [] }>()
const org = useOrgStore()
const projects = useProjectsStore()
const sessions = useSessionsStore()
const router = useRouter()

const SLUG_OK = /^[a-z0-9]+(-[a-z0-9]+)*$/

const agent = computed(() => org.byId(props.agentId))
const boss = computed(() => (agent.value?.reports_to != null ? org.byId(agent.value.reports_to) : undefined))
const bosses = computed(() => (agent.value ? org.byProject(agent.value.project_id).filter((a) => a.id !== props.agentId) : []))
const state = computed(() => (agent.value ? agentState(agent.value, sessions.all) : 'idle'))
// The icon only speaks when there is something to see; "off" is the switch and the warning, "idle" is silence.
const showState = computed(() => state.value === 'busy' || state.value === 'waiting')

const error = ref<string | null>(null)
const notice = ref<string | null>(null)
const busy = ref(false)

function begin(): boolean {
  if (busy.value) return false
  busy.value = true
  error.value = null
  notice.value = null
  return true
}

// Switch --------------------------------------------------------------------

// The switch moves at once; if the save fails it goes back to what the agent really is.
const pendingEnabled = ref<boolean | null>(null)
const enabledShown = computed(() => pendingEnabled.value ?? agent.value?.enabled ?? false)

async function setEnabled(value: boolean): Promise<void> {
  if (!begin()) return
  pendingEnabled.value = value
  try {
    org.upsertAgent(await updateAgent(props.agentId, { enabled: value }))
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    pendingEnabled.value = null
    busy.value = false
  }
}

// Switched-off warning --------------------------------------------------------

const now = ref(new Date())
const tick = setInterval(() => { now.value = new Date() }, 60_000)
onBeforeUnmount(() => clearInterval(tick))

// The routines are only read when the agent is off: that is the only time the warning needs them.
watch(
  () => (agent.value && !agent.value.enabled ? agent.value.project_id : null),
  (projectId) => { if (projectId !== null) void org.ensureRoutines(projectId).catch(() => {}) },
  { immediate: true },
)

const scheduled = computed(() =>
  agent.value
    ? org.routinesOf(agent.value.project_id).filter((r) => r.agent_id === props.agentId && r.enabled && r.schedules.length > 0)
    : [],
)
// Empty until the routines of the project are read (or when the read failed): it does not claim "nothing runs"
// about something it does not know.
const offDetail = computed(() => {
  if (!agent.value || org.routines[agent.value.project_id] === undefined) return ''
  const at = nextSlot(scheduled.value.flatMap((r) => r.schedules), now.value)
  if (!at) return 'Nada roda enquanto ele estiver assim.'
  const n = scheduled.value.length
  const lead = n === 1 ? 'A rotina continua agendada' : `As ${n} rotinas continuam agendadas`
  return `${lead}, mas a próxima (${slotLabel(at, now.value)}) não roda enquanto ele estiver assim.`
})

// Run -----------------------------------------------------------------------

const blocked = computed(() => (agent.value?.definition_error ? 'A definição do agente está inválida: corrija o AGENT.md para poder rodar.' : null))
const cannotRun = computed(() => blocked.value !== null || !agent.value?.enabled)

async function run(text?: string): Promise<void> {
  if (cannotRun.value || !begin()) return
  try {
    await wakeAgent(props.agentId, text)
    instruction.value = ''
    notice.value = 'Pedido na fila: a execução começa assim que o agente puder.'
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}

const runningWithText = ref(false)
// Kept until the request succeeds, so a failure does not lose what was typed.
const instruction = ref('')
const instructionInput = ref<HTMLInputElement | null>(null)

async function openRunText(): Promise<void> {
  runningWithText.value = true
  await nextTick()
  instructionInput.value?.focus()
}

function confirmRunText(): void {
  runningWithText.value = false
  void run(instruction.value.trim() || undefined)
}

// Boss ----------------------------------------------------------------------

const changingBoss = ref(false)
const bossChoice = ref('')

function openBoss(): void {
  bossChoice.value = String(agent.value?.reports_to ?? '')
  changingBoss.value = true
}

async function saveBoss(): Promise<void> {
  changingBoss.value = false
  if (!begin()) return
  try {
    org.upsertAgent(await updateAgent(props.agentId, { reports_to: bossChoice.value === '' ? null : Number(bossChoice.value) }))
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}

// Duplicate -----------------------------------------------------------------

const duplicating = ref(false)
const dupProject = ref('')
const dupSlug = ref('')
const dupError = ref<string | null>(null)
const dupBusy = ref(false)
const dupSlugValid = computed(() => dupSlug.value.length <= SLUG_MAX_LENGTH && SLUG_OK.test(dupSlug.value))

onMounted(() => { if (!projects.loaded && projects.regular.length === 0) void projects.load().catch(() => {}) })

function openDuplicate(): void {
  if (!agent.value) return
  const other = projects.regular.find((p) => p.id !== agent.value!.project_id) ?? projects.regular[0]
  dupProject.value = String(other?.id ?? agent.value.project_id)
  dupSlug.value = agent.value.slug || slugify(agent.value.name)
  dupError.value = null
  duplicating.value = true
}

async function duplicate(): Promise<void> {
  if (dupBusy.value || !dupSlugValid.value) return
  dupBusy.value = true
  dupError.value = null
  try {
    const copy = await duplicateAgent(props.agentId, { project_id: Number(dupProject.value), slug: dupSlug.value })
    org.upsertAgent(copy)
    duplicating.value = false
    await router.push({ name: 'agents', params: { projectId: copy.project_id }, query: { agente: String(copy.id), aba: 'definicao' } })
  } catch (e) {
    dupError.value = errorMessage(e)
  } finally {
    dupBusy.value = false
  }
}

// Delete --------------------------------------------------------------------

const confirmingDelete = ref(false)

async function remove(): Promise<void> {
  confirmingDelete.value = false
  if (!begin()) return
  try {
    await org.deleteAgent(props.agentId)
    emit('deleted')
    org.removeAgent(props.agentId)
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}

// Menu ----------------------------------------------------------------------

const menuItems = computed<MoreMenuItem[]>(() => [
  { id: 'run-with-text', label: 'Rodar com instrução…', disabled: cannotRun.value, title: cannotRun.value ? 'Ligue o agente e corrija a definição para poder rodar.' : undefined },
  { id: 'boss', label: 'Trocar chefe…' },
  { id: 'duplicate', label: 'Duplicar para outro projeto…' },
  { id: 'delete', label: 'Excluir…', danger: true },
])

function onMenu(id: string): void {
  if (id === 'run-with-text') void openRunText()
  else if (id === 'boss') openBoss()
  else if (id === 'duplicate') openDuplicate()
  else if (id === 'delete') confirmingDelete.value = true
}

const CHIP = 'rounded border border-line px-1.5 py-0.5 font-mono text-[0.6875rem] text-fg-muted'
</script>

<template>
  <header v-if="agent" data-test="agent-header" class="flex min-w-0 flex-col gap-2.5">
    <div class="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
      <ToggleSwitch data-test="agent-toggle" label="Agente ligado" :model-value="enabledShown" :disabled="busy" @update:model-value="setEnabled" />
      <AgentStateIcon v-if="showState" :state="state" :size="16" />
      <h2 class="m-0 min-w-0 truncate text-lg font-semibold tracking-tight">{{ agent.name }}</h2>
      <span v-if="agent.model" data-test="agent-model" :class="CHIP">{{ formatModelName(agent.model) }}</span>
      <span v-if="agent.effort" data-test="agent-effort" :class="CHIP">{{ agent.effort }}</span>
      <span v-if="boss" class="text-xs text-fg-muted">
        responde ao
        <RouterLink data-test="agent-boss-link" :to="{ name: 'agents', params: { projectId: boss.project_id }, query: { agente: String(boss.id) } }" class="rounded text-info-soft hover:underline focus-visible:outline-2 focus-visible:outline-primary">{{ boss.name }}</RouterLink>
      </span>
      <span class="grow" />
      <button type="button" data-test="agent-run" :class="BTN" :disabled="busy || cannotRun" :aria-describedby="blocked ? 'agent-run-blocked' : !agent.enabled ? 'agent-off' : undefined" @click="run()">Rodar agora</button>
      <MoreMenu data-test="agent-more" label="Mais ações do agente" :items="menuItems" @select="onMenu" />
    </div>

    <p v-if="agent.description" data-test="agent-description" class="m-0 max-w-prose text-sm text-fg-muted">{{ agent.description }}</p>

    <div v-if="!agent.enabled" class="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-secondary/50 bg-secondary/12 py-2 pr-2.5 pl-3.5">
      <span class="text-secondary"><IconAlert :size="15" /></span>
      <p id="agent-off" data-test="agent-off" class="m-0 min-w-0 flex-1 text-sm text-fg"><b class="font-semibold text-secondary-soft">Agente desligado.</b>{{ offDetail && ` ${offDetail}` }}</p>
      <button type="button" data-test="agent-off-enable" :disabled="busy" class="h-8 cursor-pointer rounded-lg border-0 bg-secondary px-3.5 text-[0.8125rem] font-semibold whitespace-nowrap text-secondary-fg hover:bg-secondary-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-default disabled:opacity-50" @click="setEnabled(true)">Ligar agente</button>
    </div>

    <p v-if="blocked" id="agent-run-blocked" data-test="agent-run-blocked" class="m-0 text-xs text-secondary">{{ blocked }}</p>
    <p v-if="notice" data-test="agent-run-ok" role="status" class="m-0 text-xs text-fg-muted">{{ notice }}</p>
    <p v-if="error" data-test="agent-error" role="alert" :class="ERROR">{{ error }}</p>

    <ConfirmDialog v-if="runningWithText" title="Rodar com instrução" confirm-label="Rodar" :autofocus="false" @confirm="confirmRunText" @cancel="runningWithText = false">
      <form class="flex flex-col gap-3" @submit.prevent="confirmRunText">
        <label class="flex flex-col gap-1 text-sm">
          <span class="text-fg-muted">Instrução (opcional)</span>
          <input ref="instructionInput" v-model="instruction" data-test="agent-run-text" type="text" autocomplete="off" placeholder="O que o agente deve fazer desta vez" :class="FIELD" />
        </label>
      </form>
    </ConfirmDialog>

    <ConfirmDialog v-if="changingBoss" title="Trocar chefe" confirm-label="Salvar" :confirm-disabled="bossChoice === String(agent.reports_to ?? '')" @confirm="saveBoss" @cancel="changingBoss = false">
      <label class="flex flex-col gap-1 text-sm">
        <span class="text-fg-muted">Chefe de {{ agent.name }}</span>
        <select v-model="bossChoice" data-test="agent-boss" :class="FIELD">
          <option value="">Ninguém (topo)</option>
          <option v-for="b in bosses" :key="b.id" :value="String(b.id)">{{ b.name }}</option>
        </select>
      </label>
    </ConfirmDialog>

    <ConfirmDialog v-if="confirmingDelete" :title="`Excluir ${agent.name}?`" confirm-label="Excluir" tone="danger" @confirm="remove" @cancel="confirmingDelete = false">
      <p class="m-0 text-sm text-fg-muted">O AGENT.md, a memória e os segredos do agente são apagados. As conversas continuam no histórico. Não dá para desfazer.</p>
    </ConfirmDialog>

    <ConfirmDialog v-if="duplicating" title="Duplicar para outro projeto" confirm-label="Duplicar" :confirm-disabled="!dupSlugValid || dupBusy" :autofocus="false" @confirm="duplicate" @cancel="duplicating = false">
      <form class="flex flex-col gap-3" @submit.prevent="duplicate">
        <p class="m-0 text-sm text-fg-muted">A cópia leva só o AGENT.md (sem memória, segredos nem histórico) e nasce sem chefe.</p>
        <label class="flex flex-col gap-1 text-sm">
          <span class="text-fg-muted">Projeto</span>
          <select v-model="dupProject" data-test="duplicate-project" :class="FIELD">
            <option v-for="p in projects.regular" :key="p.id" :value="String(p.id)">{{ p.name }}</option>
          </select>
        </label>
        <label class="flex flex-col gap-1 text-sm">
          <span class="text-fg-muted">Identificador</span>
          <input v-model="dupSlug" data-test="duplicate-slug" type="text" autocomplete="off" spellcheck="false" :class="[FIELD, 'font-mono text-[0.8125rem]']" />
          <span class="text-xs" :class="dupSlug && !dupSlugValid ? 'text-diff-del-fg' : 'text-fg-subtle'">Nome da pasta do agente: letras minúsculas, números e hífens, até {{ SLUG_MAX_LENGTH }} caracteres.</span>
        </label>
        <p v-if="dupError" data-test="duplicate-error" role="alert" :class="ERROR">{{ dupError }}</p>
      </form>
    </ConfirmDialog>
  </header>
</template>
