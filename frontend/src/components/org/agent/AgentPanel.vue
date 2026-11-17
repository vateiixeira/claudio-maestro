<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AgentConversations from './AgentConversations.vue'
import AgentDefinition from './AgentDefinition.vue'
import AgentHeader from './AgentHeader.vue'
import AgentMemory from './AgentMemory.vue'
import AgentRegistry from './AgentRegistry.vue'
import AgentRuns from './AgentRuns.vue'
import AgentSecrets from './AgentSecrets.vue'
import { listAgentRegistry } from '../../../api/http'
import { useOrgStore } from '../../../stores/org'
import type { DefinitionDraft } from './helpers'

// The panel of one agent: the header (who it is and what you can do with it) and its sections. The section comes from `?aba=`
// (`NewAgentDialog` opens `definicao`); the drafts of the AGENT.md and of the memory live here, so they survive
// a change of section.
const props = defineProps<{ agentId: number }>()
const org = useOrgStore()
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

// Without `aba`, an agent whose AGENT.md does not open starts in the editor. Decided once: a later error
// does not pull you out of the section you are reading.
const fallback: SectionId = agent.value?.definition_error ? 'definicao' : 'conversa'
const active = computed<SectionId>(() => SECTIONS.find((s) => s.id === route.query.aba)?.id ?? fallback)

const definitionDraft = ref<DefinitionDraft | null>(null)
const memoryDraft = ref<string | null>(null)
const hasDraft = (id: SectionId) => (id === 'definicao' ? definitionDraft.value !== null : id === 'memoria' ? memoryDraft.value !== null : false)

// How many things the agent registered, for the badge on the tab. A failed read keeps the last number.
const registryCount = ref(0)
let registryRead = 0
async function loadRegistryCount(): Promise<void> {
  const mine = ++registryRead
  try {
    const items = await listAgentRegistry(props.agentId)
    if (mine === registryRead) registryCount.value = items.length
  } catch {
    // The tab works without the number.
  }
}
onMounted(() => { void loadRegistryCount() })
watch(() => org.changes[props.agentId], () => { void loadRegistryCount() })
// The tab reports its removals; the agent also writes during a run: reread when you leave the tab or the run changes.
watch(() => org.byId(props.agentId)?.last_run?.outcome, () => { void loadRegistryCount() })
watch(active, (now, before) => { if (before === 'registro' && now !== 'registro') void loadRegistryCount() })

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
  const query = { ...route.query }
  delete query.agente
  delete query.aba
  void router.replace({ query })
}
</script>

<template>
  <div data-test="agent-panel" :data-agent-id="agentId" class="flex min-w-0 flex-col gap-4">
    <template v-if="agent">
      <AgentHeader :agent-id="agentId" @deleted="deleted" />

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
            <span v-if="section.id === 'registro' && registryCount > 0" data-test="agent-tab-count" class="ml-1.5 font-mono text-[0.6875rem] text-fg-muted">{{ registryCount }}</span>
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
          <AgentRegistry v-else-if="active === 'registro'" :agent-id="agentId" @count="registryCount = $event" />
          <AgentRuns v-else :agent-id="agentId" />
        </div>
      </div>
    </template>
  </div>
</template>
