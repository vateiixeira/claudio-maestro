<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router'
import AgentStateIcon from './AgentStateIcon.vue'
import RunHistory from './RunHistory.vue'
import { nextSlot, slotLabel } from './routines/schedule'
import { agentState, type AgentState } from '../../org'
import { useOrgStore } from '../../stores/org'
import { useSessionsStore } from '../../stores/sessions'
import type { TreeNode } from '../../stores/org'

const props = defineProps<{ node: TreeNode; selectedId: number | null; now: Date }>()
const router = useRouter()
const route = useRoute()
const sessions = useSessionsStore()
const org = useOrgStore()

const agent = computed(() => props.node.agent)
const state = computed(() => agentState(agent.value, sessions.all))
const selected = computed(() => props.selectedId === agent.value.id)

// What the agent is doing, in words, when it is not just waiting (the icon says "idle" well enough).
const STATE_TEXT: Partial<Record<AgentState, { text: string; tone: string }>> = {
  off: { text: 'desligado', tone: 'text-secondary' },
  busy: { text: 'executando', tone: 'text-primary' },
  waiting: { text: 'aguardando você', tone: 'text-secondary' },
}
const stateText = computed(() => STATE_TEXT[state.value])

// The corner of the card: the news, or else when the routines wake the agent next.
const unseenText = computed(() => `${agent.value.unseen} ${agent.value.unseen === 1 ? 'novidade' : 'novidades'}`)
const routineText = computed(() => {
  const schedules = org
    .routinesOf(agent.value.project_id)
    .filter((routine) => routine.agent_id === agent.value.id && routine.enabled)
    .flatMap((routine) => routine.schedules)
  const at = nextSlot(schedules, props.now)
  return at ? slotLabel(at, props.now) : 'sem rotina'
})

const runs = computed(() => org.runsOf(agent.value.id))

function select(): void {
  const query: LocationQueryRaw = { ...route.query, agente: String(agent.value.id) }
  delete query.aba
  void router.replace({ query })
}
</script>

<template>
  <li data-test="org-node" :data-agent-id="agent.id" class="list-none">
    <button
      type="button"
      data-test="org-node-button"
      :aria-current="selected ? 'true' : undefined"
      class="flex w-full min-w-0 cursor-pointer flex-col gap-1.5 rounded-[10px] border-0 px-3 py-2.5 text-left text-fg-muted hover:bg-card hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
      :class="selected ? 'bg-card text-fg' : 'bg-transparent'"
      @click="select"
    >
      <span class="flex min-w-0 items-center gap-2">
        <AgentStateIcon :state="state" />
        <span class="min-w-0 truncate text-sm" :class="[agent.enabled ? 'font-medium' : 'text-fg-muted', selected ? 'text-fg' : '']">{{ agent.name }}</span>
        <span class="grow" />
        <span
          v-if="agent.definition_error"
          data-test="org-node-definition-error"
          :title="agent.definition_error"
          class="flex shrink-0 items-center text-secondary"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3.5 2.5 20h19L12 3.5z" /><path d="M12 10v4M12 17v.01" /></svg>
          <span class="sr-only">Definição inválida: {{ agent.definition_error }}</span>
        </span>
        <span data-test="org-node-aside" class="shrink-0 text-xs tabular-nums">
          <span v-if="agent.unseen > 0" data-test="org-node-unseen" class="font-semibold text-secondary">{{ unseenText }}</span>
          <span v-else class="text-fg-muted">{{ routineText }}</span>
        </span>
      </span>
      <span v-if="agent.description" data-test="org-node-description" class="max-w-full truncate text-xs text-fg-subtle">{{ agent.description }}</span>
      <span v-if="runs.length > 0 || stateText" class="flex min-w-0 items-center gap-2.5">
        <RunHistory :runs="runs" />
        <span class="grow" />
        <span v-if="stateText" data-test="org-node-state" class="shrink-0 text-xs" :class="stateText.tone">{{ stateText.text }}</span>
      </span>
    </button>
    <ul v-if="node.children.length" class="m-0 ml-3.5 flex flex-col gap-0.5 border-l border-line p-0 pl-2">
      <OrgTreeNode v-for="child in node.children" :key="child.agent.id" :node="child" :selected-id="selectedId" :now="now" />
    </ul>
  </li>
</template>
