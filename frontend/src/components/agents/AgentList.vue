<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { nextRunLabel } from '../../agents'
import { useMinuteClock } from '../../minuteClock'
import type { Specialist } from '../../types/api'
import IconPlus from '../icons/IconPlus.vue'
import AgentRunIcon from './AgentRunIcon.vue'

defineProps<{ agents: Specialist[]; selectedId: number | null; loading?: boolean }>()
defineEmits<{ new: [] }>()

const now = useMinuteClock()
</script>

<template>
  <nav aria-label="Agentes" class="flex min-h-0 flex-col gap-2 border-r border-line p-3">
    <h1 class="m-0 px-1 pt-1 pb-0.5 text-[0.9375rem] font-semibold tracking-tight">Agentes</h1>
    <button
      type="button"
      data-test="agent-new"
      class="flex h-9 w-full items-center gap-2 rounded-lg border border-line-strong bg-surface px-2.5 text-left font-medium text-fg hover:bg-card focus-visible:outline-2 focus-visible:outline-primary"
      @click="$emit('new')"
    >
      <span class="text-primary"><IconPlus :size="15" /></span>
      <span class="grow">Novo agente</span>
    </button>
    <p v-if="agents.length === 0" class="m-0 px-2.5 py-2 text-sm text-fg-muted">{{ loading ? 'Carregando…' : 'Nenhum agente ainda.' }}</p>
    <ul class="m-0 flex min-h-0 list-none flex-col gap-px overflow-y-auto p-0">
      <li v-for="agent in agents" :key="agent.id">
        <RouterLink
          data-test="agent-item"
          :to="{ name: 'agents', params: { id: agent.id } }"
          :aria-current="selectedId === agent.id ? 'page' : undefined"
          class="flex min-h-[44px] items-center gap-2.5 rounded-lg px-2.5 py-1.5 no-underline hover:bg-card"
          :class="selectedId === agent.id ? 'bg-card text-fg' : 'text-fg-muted hover:text-fg'"
        >
          <AgentRunIcon data-test="agent-state" :outcome="agent.last_run?.outcome ?? null" :size="13" />
          <span class="flex min-w-0 grow flex-col">
            <span class="truncate font-medium" :class="selectedId === agent.id ? 'text-fg' : ''">{{ agent.name }}</span>
            <span data-test="agent-next" class="truncate font-mono text-[0.6875rem] text-fg-subtle">{{ nextRunLabel(agent.schedules, agent.enabled, new Date(now)) }}</span>
          </span>
        </RouterLink>
      </li>
    </ul>
  </nav>
</template>
