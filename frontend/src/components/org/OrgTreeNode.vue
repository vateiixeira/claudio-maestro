<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import AgentStateIcon from './AgentStateIcon.vue'
import { agentState } from '../../org'
import { useSessionsStore } from '../../stores/sessions'
import type { TreeNode } from '../../stores/org'

const props = defineProps<{ node: TreeNode; selectedId: number | null }>()
const router = useRouter()
const sessions = useSessionsStore()

const agent = computed(() => props.node.agent)
const state = computed(() => agentState(agent.value, sessions.all))
const selected = computed(() => props.selectedId === agent.value.id)

function select(): void {
  void router.replace({ query: { agente: String(agent.value.id) } })
}
</script>

<template>
  <li data-test="org-node" :data-agent-id="agent.id" class="list-none">
    <button
      type="button"
      data-test="org-node-button"
      :aria-current="selected ? 'true' : undefined"
      class="flex w-full min-w-0 cursor-pointer items-center gap-2 rounded-md border-0 px-2 py-1.5 text-left text-fg-muted hover:bg-card hover:text-fg focus-visible:outline-2 focus-visible:outline-primary"
      :class="selected ? 'bg-card text-fg' : 'bg-transparent'"
      @click="select"
    >
      <AgentStateIcon :state="state" />
      <span class="flex min-w-0 grow flex-col">
        <span class="truncate" :class="[agent.enabled ? 'font-medium' : 'text-fg-subtle', selected ? 'text-fg' : '']">{{ agent.name }}</span>
        <span v-if="agent.description" data-test="org-node-description" class="truncate text-xs text-fg-subtle">{{ agent.description }}</span>
      </span>
      <span
        v-if="agent.definition_error"
        data-test="org-node-definition-error"
        :title="agent.definition_error"
        class="flex shrink-0 items-center text-secondary"
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3.5 2.5 20h19L12 3.5z" /><path d="M12 10v4M12 17v.01" /></svg>
        <span class="sr-only">Definição inválida: {{ agent.definition_error }}</span>
      </span>
      <span v-if="agent.unseen > 0" data-test="org-node-unseen" class="shrink-0 text-xs font-semibold text-secondary">
        <span aria-hidden="true">{{ agent.unseen }}</span><span class="sr-only">{{ agent.unseen }} {{ agent.unseen === 1 ? 'novidade' : 'novidades' }}</span>
      </span>
    </button>
    <ul v-if="node.children.length" class="m-0 ml-3 flex flex-col gap-px border-l border-line p-0 pl-1.5">
      <OrgTreeNode v-for="child in node.children" :key="child.agent.id" :node="child" :selected-id="selectedId" />
    </ul>
  </li>
</template>
