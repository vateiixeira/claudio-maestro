<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AgentStateIcon from '../org/AgentStateIcon.vue'
import { sidebarItemClass } from './itemClass'
import { errorMessage } from '../../api/http'
import { agentState } from '../../org'
import { useOrgStore } from '../../stores/org'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import type { Agent } from '../../types/org'

// The agents above the projects, grouped by project: a click opens the agent's main conversation, a permanent session.
const org = useOrgStore()
const projects = useProjectsStore()
const sessions = useSessionsStore()
const route = useRoute()
const router = useRouter()

const opening = ref<number | null>(null)
const error = ref<string | null>(null)

const groups = computed(() =>
  projects.projects
    .map((project) => ({
      project,
      rows: org.byProject(project.id).map((agent) => ({ agent, state: agentState(agent, sessions.all) })),
    }))
    .filter((group) => group.rows.length > 0),
)
const isCurrent = (agent: Agent) =>
  route.name === 'session' && agent.main_session_id != null && route.params.id === agent.main_session_id

// Layout of the shared sidebar item; a disabled agent is dimmed (the current one keeps the highlight).
function rowClass(agent: Agent): string[] {
  const [layout] = sidebarItemClass(false)
  if (isCurrent(agent)) return [layout!, 'bg-card text-fg']
  return [layout!, agent.enabled ? 'text-fg-muted hover:text-fg' : 'text-fg-subtle hover:text-fg']
}

async function open(agent: Agent) {
  if (opening.value !== null) return
  opening.value = agent.id
  error.value = null
  try {
    await org.openMain(agent.id, router)
  } catch (e) {
    error.value = `Não foi possível abrir a conversa de ${agent.name}. ${errorMessage(e)}`
  } finally {
    opening.value = null
  }
}
</script>

<template>
  <section v-if="groups.length" data-test="sidebar-agents" aria-labelledby="sidebar-agents-title" class="flex flex-col gap-px">
    <div class="flex h-[30px] items-center pl-2.5">
      <h2 id="sidebar-agents-title" data-test="section-title" class="font-mono text-[0.6875rem] font-normal tracking-[0.08em] text-fg-subtle uppercase">Agentes</h2>
    </div>
    <p v-if="error" data-test="sidebar-agents-error" role="alert" class="m-0 px-2.5 py-1 text-xs text-diff-del-fg">{{ error }}</p>
    <template v-for="group in groups" :key="group.project.id">
      <h3 data-test="sidebar-agent-project" class="m-0 truncate px-2.5 pt-1.5 pb-0.5 text-xs font-medium text-fg-subtle">{{ group.project.name }}</h3>
      <button
        v-for="{ agent, state } in group.rows"
        :key="agent.id"
        type="button"
        data-test="sidebar-agent-row"
        :aria-current="isCurrent(agent) ? 'page' : undefined"
        :class="[rowClass(agent), 'w-full cursor-pointer border-none bg-transparent text-left focus-visible:outline-2 focus-visible:outline-primary']"
        @click="open(agent)"
      >
        <AgentStateIcon :state="state" :size="12" />
        <span data-test="sidebar-agent-name" class="min-w-0 truncate" :class="agent.enabled ? 'font-medium' : ''">{{ agent.name }}</span>
        <span class="grow" />
        <span v-if="agent.unseen > 0" class="flex shrink-0 items-center text-xs font-semibold text-secondary">
          <span data-test="sidebar-agent-unseen" aria-hidden="true">{{ agent.unseen }}</span><span class="sr-only">{{ agent.unseen }} {{ agent.unseen === 1 ? 'novidade' : 'novidades' }}</span>
        </span>
      </button>
    </template>
  </section>
</template>
