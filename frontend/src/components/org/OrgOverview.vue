<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watchEffect } from 'vue'
import { RouterLink } from 'vue-router'
import RunHistory from './RunHistory.vue'
import { BTN } from './styles'
import { historyBars } from './runHistory'
import { nextSlot, slotLabel } from './routines/schedule'
import GroupHeader from '../ui/GroupHeader.vue'
import { useOrgStore, type TreeNode } from '../../stores/org'
import { useProjectsStore } from '../../stores/projects'
import type { Agent } from '../../types/org'

// Every project at a glance: the ones that have an organization, with how their agents are doing, and the ones
// that still have none. The embedded "no project" folder is not a project of the organization.
const org = useOrgStore()
const projects = useProjectsStore()

// The clock behind "hoje 18:40": it moves every minute so the next slot never stays in the past.
const now = ref(new Date())
const tick = setInterval(() => { now.value = new Date() }, 60_000)
onBeforeUnmount(() => clearInterval(tick))

interface Line { agent: Agent; depth: number }
interface Card {
  id: number
  name: string
  color: string
  lines: Line[]
  meta: string
  unseen: number
}

function flatten(nodes: TreeNode[], depth = 0): Line[] {
  return nodes.flatMap((node) => [{ agent: node.agent, depth }, ...flatten(node.children, depth + 1)])
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

const cards = computed<Card[]>(() =>
  projects.regular
    .map((project) => {
      const lines = flatten(org.tree(project.id))
      const off = lines.filter((line) => !line.agent.enabled).length
      return {
        id: project.id,
        name: project.name,
        color: project.color,
        lines,
        meta: off > 0 ? `${plural(lines.length, 'agente', 'agentes')} · ${plural(off, 'desligado', 'desligados')}` : plural(lines.length, 'agente', 'agentes'),
        unseen: lines.reduce((sum, line) => sum + line.agent.unseen, 0),
      }
    })
    .filter((card) => card.lines.length > 0),
)
const without = computed(() => projects.regular.filter((project) => !cards.value.some((card) => card.id === project.id)))

// The realtime load may not have run (it stops when the projects fail to load): ask for the agents. If it is already
// under way, the newest read wins (the store keeps a ticket).
if (!org.loaded && !org.error) void org.load()

// The rows show the run history and the next routine slot: read them once. A failure leaves the row without them.
watchEffect(() => {
  for (const card of cards.value) {
    void org.ensureRoutines(card.id).catch(() => {})
    for (const line of card.lines) void org.ensureRuns(line.agent.id).catch(() => {})
  }
})

/** The runs of the agent were read: only then "sem execuções" is true. */
const runsRead = (agent: Agent): boolean => org.runs[agent.id] !== undefined

function hasHistory(agent: Agent): boolean {
  return historyBars(org.runsOf(agent.id)).length > 0
}

function nextText(agent: Agent): string {
  if (!agent.enabled) return 'desligado'
  // Nothing is said until the routines of the project are read.
  if (org.routines[agent.project_id] === undefined) return ''
  const schedules = org
    .routinesOf(agent.project_id)
    .filter((routine) => routine.agent_id === agent.id && routine.enabled)
    .flatMap((routine) => routine.schedules)
  const at = nextSlot(schedules, now.value)
  return at ? slotLabel(at, now.value) : 'sob demanda'
}

const COLUMNS = 'grid grid-cols-[minmax(0,1fr)_6.5rem_7.5rem] items-center gap-x-5 md:grid-cols-[minmax(0,1fr)_9.375rem_7.5rem_9.375rem]'
const FOCUS = 'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary'
</script>

<template>
  <div data-test="org-overview" class="flex flex-col gap-7">
    <div v-if="org.error" data-test="org-overview-error" class="flex flex-wrap items-center gap-3">
      <p role="alert" class="m-0 text-sm text-diff-del-fg">Não foi possível carregar os agentes. {{ org.error }}</p>
      <button type="button" data-test="org-overview-retry" :class="BTN" @click="org.load()">Tentar de novo</button>
    </div>
    <p v-else-if="!org.loaded" role="status" class="m-0 text-fg-muted">Carregando agentes…</p>

    <template v-if="org.loaded">
      <section v-if="cards.length > 0" data-test="org-overview-with" aria-label="Com organização">
        <GroupHeader title="Com organização" :count="cards.length" />
        <ul class="m-0 mt-3 flex list-none flex-col gap-3 p-0">
          <li v-for="card in cards" :key="card.id" data-test="org-overview-project" :data-project-id="card.id" class="rounded-xl border border-line-strong bg-panel px-[18px] pt-1 pb-1.5">
            <RouterLink
              :to="`/agentes/${card.id}`"
              data-test="org-project-option"
              class="flex min-w-0 items-center gap-3 rounded-lg py-3.5 text-fg no-underline hover:text-primary-soft"
              :class="FOCUS"
            >
              <span class="size-2.5 shrink-0 rounded-[3px]" :style="{ backgroundColor: card.color }" aria-hidden="true" />
              <span class="min-w-0 truncate text-[1.0625rem] font-semibold tracking-tight">{{ card.name }}</span>
              <span data-test="org-overview-meta" class="shrink-0 font-mono text-[0.71875rem] text-fg-muted tabular-nums">{{ card.meta }}</span>
              <span class="grow" />
              <span v-if="card.unseen > 0" data-test="org-overview-unseen" class="shrink-0 text-[0.8125rem] text-secondary">{{ plural(card.unseen, 'novidade', 'novidades') }}</span>
              <svg class="shrink-0 text-fg-muted" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 6 6 6-6 6" /></svg>
            </RouterLink>
            <div :class="[COLUMNS, 'h-[30px] font-mono text-[0.65625rem] font-semibold tracking-[0.08em] text-fg-muted uppercase']" aria-hidden="true">
              <span>Agente</span>
              <span class="hidden md:block">Últimas execuções</span>
              <span>Novidades</span>
              <span class="text-right">Próxima</span>
            </div>
            <RouterLink
              v-for="line in card.lines"
              :key="line.agent.id"
              :to="{ path: `/agentes/${card.id}`, query: { agente: String(line.agent.id) } }"
              data-test="org-overview-agent"
              :data-agent-id="line.agent.id"
              :class="[COLUMNS, 'min-h-[46px] border-t border-line text-[0.84375rem] text-fg no-underline hover:bg-card', FOCUS]"
            >
              <span class="flex min-w-0 items-baseline gap-2.5" :style="{ paddingLeft: `${line.depth}rem` }">
                <span class="shrink-0 font-medium">{{ line.agent.name }}</span>
                <span v-if="line.agent.description" class="min-w-0 truncate text-fg-muted">{{ line.agent.description }}</span>
              </span>
              <span class="hidden md:block">
                <RunHistory v-if="hasHistory(line.agent)" :runs="org.runsOf(line.agent.id)" />
                <span v-else-if="runsRead(line.agent)" data-test="org-overview-history" class="font-mono text-[0.71875rem] text-fg-muted">sem execuções</span>
              </span>
              <span data-test="org-overview-agent-unseen" class="font-mono text-[0.71875rem] tabular-nums" :class="line.agent.unseen > 0 ? 'text-secondary' : 'text-fg-muted'">{{ line.agent.unseen > 0 ? line.agent.unseen : 'nenhuma' }}</span>
              <span data-test="org-overview-next" class="text-right font-mono text-[0.71875rem] tabular-nums" :class="line.agent.enabled ? 'text-fg-muted' : 'text-secondary'">{{ nextText(line.agent) }}</span>
            </RouterLink>
          </li>
        </ul>
      </section>

      <section v-if="without.length > 0 && !org.error" data-test="org-overview-without" aria-label="Sem organização">
        <GroupHeader title="Sem organização" :count="without.length">
          <span class="hidden text-xs text-fg-muted md:inline">Criar uma organização dá ao projeto um agente no topo, que recebe objetivos e tarefas.</span>
        </GroupHeader>
        <ul class="m-0 mt-2.5 grid list-none grid-cols-1 gap-x-5 gap-y-0.5 p-0 md:grid-cols-2 xl:grid-cols-3">
          <li v-for="project in without" :key="project.id" class="min-w-0">
            <RouterLink
              :to="`/agentes/${project.id}`"
              data-test="org-project-option"
              class="flex h-10 min-w-0 items-center gap-2.5 rounded-[10px] px-2.5 text-sm text-fg-muted no-underline hover:bg-panel hover:text-fg"
              :class="FOCUS"
            >
              <span class="size-2.5 shrink-0 rounded-[3px]" :style="{ backgroundColor: project.color }" aria-hidden="true" />
              <span class="min-w-0 truncate">{{ project.name }}</span>
              <span class="grow" />
              <span class="shrink-0 text-[0.78125rem]">Criar</span>
            </RouterLink>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>
