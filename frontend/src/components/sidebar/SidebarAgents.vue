<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AgentBadge from '../agents/AgentBadge.vue'
import { sidebarItemClass } from './itemClass'
import { errorMessage } from '../../api/http'
import { agentAttention } from '../../agents'
import { useSessionsStore } from '../../stores/sessions'
import { useSpecialistsStore } from '../../stores/specialists'
import type { Specialist } from '../../types/api'

// One row per agent, above the projects: it opens the agent's main conversation, a permanent session.
const specialists = useSpecialistsStore()
const sessions = useSessionsStore()
const route = useRoute()
const router = useRouter()

const opening = ref<number | null>(null)
const error = ref<string | null>(null)

const rows = computed(() =>
  specialists.list.map((agent) => ({ agent, count: agentAttention(agent, sessions.all) })),
)
const isCurrent = (agent: Specialist) =>
  route.name === 'session' && agent.main_session_id != null && route.params.id === agent.main_session_id

// Layout of the shared sidebar item; a disabled agent is dimmed (the current one keeps the highlight).
function rowClass(agent: Specialist): string[] {
  const [layout] = sidebarItemClass(false)
  if (isCurrent(agent)) return [layout!, 'bg-card text-fg']
  return [layout!, agent.enabled ? 'text-fg-muted hover:text-fg' : 'text-fg-subtle hover:text-fg']
}

async function open(agent: Specialist) {
  if (opening.value !== null) return
  opening.value = agent.id
  error.value = null
  try {
    await specialists.openMain(agent.id, router)
  } catch (e) {
    error.value = `Não foi possível abrir a conversa de ${agent.name}. ${errorMessage(e)}`
  } finally {
    opening.value = null
  }
}
</script>

<template>
  <section v-if="rows.length" data-test="sidebar-agents" aria-labelledby="sidebar-agents-title" class="flex flex-col gap-px">
    <div class="flex h-[30px] items-center pl-2.5">
      <h2 id="sidebar-agents-title" data-test="section-title" class="font-mono text-[0.6875rem] font-normal tracking-[0.08em] text-fg-subtle uppercase">Agentes</h2>
    </div>
    <p v-if="error" data-test="sidebar-agents-error" role="alert" class="m-0 px-2.5 py-1 text-xs text-diff-del-fg">{{ error }}</p>
    <button
      v-for="{ agent, count } in rows"
      :key="agent.id"
      type="button"
      data-test="sidebar-agent-row"
      :aria-current="isCurrent(agent) ? 'page' : undefined"
      :class="[rowClass(agent), 'w-full cursor-pointer border-none bg-transparent text-left focus-visible:outline-2 focus-visible:outline-primary']"
      @click="open(agent)"
    >
      <span data-test="sidebar-agent-name" class="min-w-0 truncate" :class="agent.enabled ? 'font-medium' : ''">{{ agent.name }}</span>
      <AgentBadge :specialist-id="agent.id" />
      <span class="grow" />
      <span v-if="!agent.enabled" class="sr-only">desligado</span>
      <span v-if="count > 0" class="flex shrink-0 items-center text-xs font-semibold text-secondary">
        <span data-test="sidebar-agent-unseen" aria-hidden="true">{{ count }}</span><span class="sr-only">{{ count }} {{ count === 1 ? 'pendência' : 'pendências' }}</span>
      </span>
    </button>
  </section>
</template>
