<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import AgentStateIcon from '../AgentStateIcon.vue'
import AgentActions from './AgentActions.vue'
import AgentConversations from './AgentConversations.vue'
import AgentDefinition from './AgentDefinition.vue'
import AgentMemory from './AgentMemory.vue'
import AgentRegistry from './AgentRegistry.vue'
import AgentRuns from './AgentRuns.vue'
import AgentSecrets from './AgentSecrets.vue'
import { formatModelName } from '../../../format'
import { agentState } from '../../../org'
import { useOrgStore } from '../../../stores/org'
import { useSessionsStore } from '../../../stores/sessions'
import type { DefinitionDraft } from './helpers'

// The panel of one agent: who it is, what you can do with it, and its sections. The section comes from `?aba=`
// (`NewAgentDialog` opens `definicao`); the drafts of the AGENT.md and of the memory live here, so they survive
// a change of section.
const props = defineProps<{ agentId: number }>()
const org = useOrgStore()
const sessions = useSessionsStore()
const route = useRoute()
const router = useRouter()

const SECTIONS = [
  { id: 'conversa', label: 'Conversa' },
  { id: 'definicao', label: 'Definição' },
  { id: 'memoria', label: 'Memória' },
  { id: 'segredos', label: 'Segredos' },
  { id: 'registro', label: 'Registro' },
  { id: 'execucoes', label: 'Execuções' },
] as const
type SectionId = (typeof SECTIONS)[number]['id']

const agent = computed(() => org.byId(props.agentId))
const state = computed(() => (agent.value ? agentState(agent.value, sessions.all) : 'idle'))
const boss = computed(() => (agent.value?.reports_to != null ? org.byId(agent.value.reports_to) : undefined))

// Without `aba`, an agent whose AGENT.md does not open starts in the editor. Decided once: a later error
// does not pull you out of the section you are reading.
const fallback: SectionId = agent.value?.definition_error ? 'definicao' : 'conversa'
const active = computed<SectionId>(() => SECTIONS.find((s) => s.id === route.query.aba)?.id ?? fallback)

const definitionDraft = ref<DefinitionDraft | null>(null)
const memoryDraft = ref<string | null>(null)
const hasDraft = (id: SectionId) => (id === 'definicao' ? definitionDraft.value !== null : id === 'memoria' ? memoryDraft.value !== null : false)

const buttons = ref<HTMLButtonElement[]>([])

function select(id: SectionId): void {
  if (id === active.value && route.query.aba === id) return
  void router.replace({ query: { ...route.query, aba: id } })
}

// Arrow keys move between the tabs (the selected tab is the only one in the tab order).
async function onKey(event: KeyboardEvent, index: number): Promise<void> {
  const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
  if (step === 0 && event.key !== 'Home' && event.key !== 'End') return
  const target = event.key === 'Home' ? 0 : event.key === 'End' ? SECTIONS.length - 1 : (index + step + SECTIONS.length) % SECTIONS.length
  event.preventDefault()
  select(SECTIONS[target]!.id)
  await nextTick()
  buttons.value[target]?.focus()
}

/** After deleting: back to the tree. */
function deleted(): void {
  void router.replace({ query: {} })
}
</script>

<template>
  <div data-test="agent-panel" :data-agent-id="agentId" class="flex min-w-0 flex-col gap-4">
    <template v-if="agent">
      <header class="flex min-w-0 flex-col gap-1.5">
        <div class="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
          <AgentStateIcon :state="state" :size="16" />
          <h2 class="m-0 min-w-0 truncate text-lg font-semibold tracking-tight">{{ agent.name }}</h2>
          <span v-if="!agent.enabled" class="text-xs text-fg-subtle">Desligado</span>
          <span v-if="agent.model" data-test="agent-model" class="rounded border border-line px-1.5 py-0.5 font-mono text-[0.6875rem] text-fg-muted">{{ formatModelName(agent.model) }}</span>
          <span v-if="agent.effort" data-test="agent-effort" class="rounded border border-line px-1.5 py-0.5 font-mono text-[0.6875rem] text-fg-muted">{{ agent.effort }}</span>
        </div>
        <p v-if="agent.description" data-test="agent-description" class="m-0 max-w-prose text-sm text-fg-muted">{{ agent.description }}</p>
        <p v-if="boss" class="m-0 text-xs text-fg-subtle">
          Chefe:
          <RouterLink data-test="agent-boss-link" :to="{ name: 'agents', params: { projectId: boss.project_id }, query: { agente: String(boss.id) } }" class="rounded text-info-soft hover:underline focus-visible:outline-2 focus-visible:outline-primary">{{ boss.name }}</RouterLink>
        </p>
      </header>

      <AgentActions :agent-id="agentId" @deleted="deleted" />

      <div class="flex min-w-0 flex-col gap-4">
        <div role="tablist" aria-label="Seções do agente" class="flex gap-1 overflow-x-auto border-b border-line">
          <button
            v-for="(section, index) in SECTIONS"
            :key="section.id"
            :ref="(el) => { if (el) buttons[index] = el as HTMLButtonElement }"
            type="button"
            role="tab"
            :id="`agent-tab-${section.id}`"
            :data-test="`agent-tab-${section.id}`"
            :aria-selected="active === section.id"
            aria-controls="agent-tabpanel"
            :tabindex="active === section.id ? 0 : -1"
            class="-mb-px h-9 shrink-0 cursor-pointer border-0 border-b-2 bg-transparent px-3 text-sm font-medium hover:text-fg focus-visible:outline-2 focus-visible:outline-primary"
            :class="active === section.id ? 'border-primary text-fg' : 'border-transparent text-fg-muted'"
            @click="select(section.id)"
            @keydown="onKey($event, index)"
          >
            {{ section.label }}
            <template v-if="hasDraft(section.id)">
              <span aria-hidden="true" class="ml-1 text-secondary">•</span>
              <span class="sr-only"> (rascunho não salvo)</span>
            </template>
          </button>
        </div>
        <div id="agent-tabpanel" role="tabpanel" :aria-labelledby="`agent-tab-${active}`" class="min-w-0">
          <AgentConversations v-if="active === 'conversa'" :agent-id="agentId" />
          <AgentDefinition v-else-if="active === 'definicao'" v-model:draft="definitionDraft" :agent-id="agentId" />
          <AgentMemory v-else-if="active === 'memoria'" v-model:draft="memoryDraft" :agent-id="agentId" />
          <AgentSecrets v-else-if="active === 'segredos'" :agent-id="agentId" />
          <AgentRegistry v-else-if="active === 'registro'" :agent-id="agentId" />
          <AgentRuns v-else :agent-id="agentId" />
        </div>
      </div>
    </template>
  </div>
</template>
