<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import ConfirmDialog from '../../ConfirmDialog.vue'
import { deleteAgent, duplicateAgent, errorMessage, updateAgent, wakeAgent } from '../../../api/http'
import { SLUG_MAX_LENGTH, slugify } from '../../../org'
import { useOrgStore } from '../../../stores/org'
import { useProjectsStore } from '../../../stores/projects'
import { BTN, BTN_PRIMARY, BTN_SMALL, ERROR, FIELD } from '../styles'
import type { Agent } from '../../../types/org'

// What you do with an agent: run it now, turn it off or on, change its boss, copy it to another project, delete it.
const props = defineProps<{ agentId: number }>()
const emit = defineEmits<{ deleted: [] }>()
const org = useOrgStore()
const projects = useProjectsStore()
const router = useRouter()

const DANGER_SMALL = 'h-7 rounded-md border border-diff-del-fg/45 bg-transparent px-2.5 text-xs font-medium text-diff-del-fg hover:bg-diff-del-bg focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-default disabled:opacity-50'
const SLUG_OK = /^[a-z0-9]+(-[a-z0-9]+)*$/

const agent = computed(() => org.byId(props.agentId))
const bosses = computed(() => (agent.value ? org.byProject(agent.value.project_id).filter((a) => a.id !== props.agentId) : []))

const error = ref<string | null>(null)
const notice = ref<string | null>(null)
const busy = ref(false)

/** Shows the agent the API answered with right away; the `agent.changed` event rereads it later. */
function apply(updated: Agent): void {
  const index = org.agents.findIndex((a) => a.id === updated.id)
  if (index >= 0) org.agents.splice(index, 1, updated)
  else org.agents.push(updated)
}

function begin(): boolean {
  if (busy.value) return false
  busy.value = true
  error.value = null
  notice.value = null
  return true
}

// Run now -------------------------------------------------------------------

const instruction = ref('')
const blocked = computed(() => {
  if (agent.value?.definition_error) return 'A definição do agente está inválida: corrija o AGENT.md para poder rodar.'
  if (agent.value && !agent.value.enabled) return 'O agente está desligado: ligue-o para poder rodar.'
  return null
})

async function run(): Promise<void> {
  if (blocked.value || !begin()) return
  try {
    const text = instruction.value.trim()
    await wakeAgent(props.agentId, text || undefined)
    instruction.value = ''
    notice.value = 'Pedido na fila: a execução começa assim que o agente puder.'
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}

async function toggle(): Promise<void> {
  if (!agent.value || !begin()) return
  try {
    apply(await updateAgent(props.agentId, { enabled: !agent.value.enabled }))
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}

// Boss ----------------------------------------------------------------------

const boss = ref(String(agent.value?.reports_to ?? ''))
watch(() => agent.value?.reports_to, (value) => { boss.value = String(value ?? '') })

async function changeBoss(event: Event): Promise<void> {
  const raw = (event.target as HTMLSelectElement).value
  if (!begin()) {
    boss.value = String(agent.value?.reports_to ?? '')
    return
  }
  try {
    apply(await updateAgent(props.agentId, { reports_to: raw === '' ? null : Number(raw) }))
  } catch (e) {
    error.value = errorMessage(e)
    // The select goes back to the boss the agent really has.
    boss.value = String(agent.value?.reports_to ?? '')
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

onMounted(() => { if (!projects.loaded && projects.projects.length === 0) void projects.load().catch(() => {}) })

function openDuplicate(): void {
  if (!agent.value) return
  const other = projects.projects.find((p) => p.id !== agent.value!.project_id) ?? projects.projects[0]
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
    apply(copy)
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
    await deleteAgent(props.agentId)
    emit('deleted')
    org.agents = org.agents.filter((a) => a.id !== props.agentId)
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div v-if="agent" data-test="agent-actions" class="flex min-w-0 flex-col gap-3">
    <div class="flex flex-wrap items-end gap-2">
      <label class="flex min-w-48 max-w-md grow flex-col gap-1 text-xs text-fg-subtle">
        <span>Instrução (opcional)</span>
        <input v-model="instruction" data-test="agent-run-text" type="text" autocomplete="off" placeholder="O que o agente deve fazer desta vez" :disabled="busy" :class="FIELD" @keydown.enter.prevent="run" />
      </label>
      <button type="button" data-test="agent-run" :class="BTN_PRIMARY" :disabled="busy || blocked !== null" :aria-describedby="blocked ? 'agent-run-blocked' : undefined" @click="run">Rodar agora</button>
      <button type="button" data-test="agent-toggle" :class="BTN" :disabled="busy" @click="toggle">{{ agent.enabled ? 'Desligar' : 'Ligar' }}</button>
    </div>
    <p v-if="blocked" id="agent-run-blocked" data-test="agent-run-blocked" class="m-0 text-xs text-secondary">{{ blocked }}</p>
    <p v-if="notice" data-test="agent-run-ok" role="status" class="m-0 text-xs text-fg-muted">{{ notice }}</p>

    <div class="flex flex-wrap items-end gap-x-3 gap-y-2">
      <label class="flex flex-col gap-1 text-xs text-fg-subtle">
        <span>Chefe</span>
        <select v-model="boss" data-test="agent-boss" :disabled="busy" :class="[FIELD, 'h-7 max-w-52 py-0 text-xs']" @change="changeBoss">
          <option value="">Ninguém (topo)</option>
          <option v-for="b in bosses" :key="b.id" :value="String(b.id)">{{ b.name }}</option>
        </select>
      </label>
      <button type="button" data-test="agent-duplicate" :class="BTN_SMALL" :disabled="busy" @click="openDuplicate">Duplicar para outro projeto</button>
      <button type="button" data-test="agent-delete" :class="DANGER_SMALL" :disabled="busy" @click="confirmingDelete = true">Excluir</button>
    </div>

    <p v-if="error" data-test="agent-error" role="alert" :class="ERROR">{{ error }}</p>

    <ConfirmDialog v-if="confirmingDelete" :title="`Excluir ${agent.name}?`" confirm-label="Excluir" tone="danger" @confirm="remove" @cancel="confirmingDelete = false">
      <p class="m-0 text-sm text-fg-muted">O AGENT.md, a memória e os segredos do agente são apagados. As conversas continuam no histórico. Não dá para desfazer.</p>
    </ConfirmDialog>

    <ConfirmDialog v-if="duplicating" title="Duplicar para outro projeto" confirm-label="Duplicar" :confirm-disabled="!dupSlugValid || dupBusy" :autofocus="false" @confirm="duplicate" @cancel="duplicating = false">
      <form class="flex flex-col gap-3" @submit.prevent="duplicate">
        <p class="m-0 text-sm text-fg-muted">A cópia leva só o AGENT.md (sem memória, segredos nem histórico) e nasce sem chefe.</p>
        <label class="flex flex-col gap-1 text-sm">
          <span class="text-fg-muted">Projeto</span>
          <select v-model="dupProject" data-test="duplicate-project" :class="FIELD">
            <option v-for="p in projects.projects" :key="p.id" :value="String(p.id)">{{ p.name }}</option>
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
  </div>
</template>
