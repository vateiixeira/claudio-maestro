<script setup lang="ts">
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { errorMessage, sendMessage } from '../api/http'
import { AGENTS_NAVIGATION_KEY } from '../agentsNavigation'
import { deliveryTitle, formatTime, localDay } from '../deliveries'
import { useDeliveriesStore } from '../stores/deliveries'
import { useOrgStore } from '../stores/org'
import { useProjectsStore } from '../stores/projects'
import { useSessionsStore } from '../stores/sessions'
import { needsYou } from '../conversation/needsYou'
import { isDiscarded, markLane } from '../conversation/marks'
import { goalDrafts } from '../goalDrafts'
import { useMinuteClock } from '../minuteClock'
import { isMacPlatform } from '../platform'
import DecisionCard from '../components/org/tasks/DecisionCard.vue'
import StartSessionRow from '../components/start/StartSessionRow.vue'
import ClaudeAuthStatus from '../components/start/ClaudeAuthStatus.vue'
import FilterChip from '../components/ui/FilterChip.vue'
import { BTN, BTN_PRIMARY, ERROR } from '../components/org/styles'

// The hint shows the key of the user's system; the field accepts both.
const submitKey = isMacPlatform() ? '⌘' : 'Ctrl'
const COLUMN_ROWS = 8
const DELIVERED_ROWS = 4
const PROJECT_CHIPS = 3

const org = useOrgStore()
const projects = useProjectsStore()
const sessions = useSessionsStore()
const deliveries = useDeliveriesStore()
const router = useRouter()
const route = useRoute()
const navigation = inject(AGENTS_NAVIGATION_KEY, undefined)

const selected = ref(typeof route.query.projeto === 'string' ? route.query.projeto : '')
const goal = computed({
  get: () => goalDrafts[selected.value] ?? '',
  set: (value: string) => { goalDrafts[selected.value] = value },
})
watch(selected, (value, before) => {
  void router.replace({ query: { ...route.query, projeto: value || undefined } })
  // What was typed before choosing a project goes to the first one chosen.
  if (!before && value && goalDrafts[''] && !goalDrafts[value]) {
    goalDrafts[value] = goalDrafts['']
    delete goalDrafts['']
  }
})

// The agent that receives the objective: the one with no boss in the project.
const top = computed(() => (selected.value ? org.topOf(Number(selected.value)) : undefined))
const noTop = computed(() => !!selected.value && org.loaded && !top.value)

// The three projects with the most recent conversation; a project picked from "Outro…" takes the third place.
const latestActivity = computed(() => {
  const latest = new Map<number, number>()
  for (const s of sessions.all) latest.set(s.project_id, Math.max(latest.get(s.project_id) ?? 0, s.last_activity_at))
  return latest
})
const recentProjects = computed(() =>
  projects.projects
    .filter((p) => p.available && p.kind === 'regular')
    .map((p, index) => ({ p, index, at: latestActivity.value.get(p.id) ?? 0 }))
    .sort((a, b) => b.at - a.at || a.index - b.index)
    .slice(0, PROJECT_CHIPS)
    .map((x) => x.p),
)
const chips = computed(() => {
  const base = recentProjects.value
  const picked = selected.value ? projects.byId(Number(selected.value)) : undefined
  if (!picked || base.some((p) => p.id === picked.id)) return base
  return [...base.slice(0, PROJECT_CHIPS - 1), picked]
})
function toggleProject(id: number) {
  selected.value = selected.value === String(id) ? '' : String(id)
}
function pickOther(event: Event) {
  const select = event.target as HTMLSelectElement
  if (select.value) selected.value = select.value
  select.value = ''
}

const busy = ref(false)
const error = ref('')
let alive = true

async function submit() {
  const projectKey = selected.value
  const projectId = Number(projectKey)
  const text = goal.value.trim()
  const agent = top.value
  if (!projectId || !text || !agent || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const sessionId = await org.openMain(agent.id)
    await sendMessage(sessionId, text)
    goalDrafts[projectKey] = ''
    if (alive) await router.push({ name: 'agents', params: { projectId }, query: { agente: String(agent.id), aba: 'conversa' } })
  } catch (e) {
    error.value = `${errorMessage(e)} O objetivo foi preservado. Confira a conversa antes de repetir o envio.`
  } finally {
    busy.value = false
  }
}

// "Com você": news from the agents, pending decisions and the conversations waiting for the user (the ones that ask first).
const unreadByAgent = computed(() => {
  const counts = new Map<number, number>()
  for (const n of org.notices) if (n.read_at === null) counts.set(n.agent_id, (counts.get(n.agent_id) ?? 0) + 1)
  return [...counts]
    .map(([id, count]) => ({ name: org.byId(id)?.name ?? 'Outro agente', count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, 'pt-BR'))
})
const unreadTotal = computed(() => unreadByAgent.value.reduce((sum, a) => sum + a.count, 0))
const unreadText = computed(() => unreadByAgent.value.map((a) => `${a.name} ${a.count}`).join(' · '))
const waiting = computed(() =>
  sessions.all
    .filter((s) => s.display_state === 'waiting' && markLane(s) === 'now')
    .sort((a, b) => Number(needsYou(b)) - Number(needsYou(a))),
)
const withYouText = computed(() => {
  const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`
  return [
    waiting.value.length ? plural(waiting.value.length, 'conversa', 'conversas') : '',
    org.decisionsPending.length ? plural(org.decisionsPending.length, 'decisão', 'decisões') : '',
    unreadTotal.value ? plural(unreadTotal.value, 'novidade', 'novidades') : '',
  ].filter(Boolean).join(' · ')
})

const running = computed(() => sessions.all.filter((s) => s.display_state === 'running' && !isDiscarded(s)))

// "Entregue hoje": the store is shared with the Entregas screen, which may have left another day in it.
// The day follows the clock, so a screen left open past midnight moves on to the new day.
const clock = useMinuteClock()
const today = computed(() => localDay(new Date(clock.value)))
const delivered = computed(() => (deliveries.day?.date === today.value ? [...deliveries.day.deliveries].sort((a, b) => a.finished_at - b.finished_at) : null))
const deliveredShown = computed(() => (delivered.value ?? []).slice(-DELIVERED_ROWS))
const deliveredProjects = computed(() => new Set((delivered.value ?? []).map((d) => d.project_id)).size)
const deliveredText = computed(() => {
  const n = delivered.value?.length ?? 0
  return n ? `${n} em ${deliveredProjects.value} ${deliveredProjects.value === 1 ? 'projeto' : 'projetos'}` : ''
})
const reloadDeliveries = () => deliveries.load(today.value)
void reloadDeliveries()
watch(today, () => { void reloadDeliveries() })
onBeforeUnmount(() => {
  alive = false
  deliveries.release()
})

const SECTION = 'flex min-w-0 flex-col'
const SECTION_HEAD = 'flex h-[34px] items-center gap-2 border-b border-line-strong'
const SECTION_TITLE = 'm-0 text-[0.9375rem] font-semibold tracking-tight'
const SECTION_COUNT = 'font-mono text-[0.71875rem] text-fg-subtle tabular-nums'
const LINK = 'text-[0.8125rem] whitespace-nowrap text-info-soft no-underline hover:text-fg hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary'
const EMPTY = 'm-0 border-b border-line py-6 text-[0.8125rem] leading-relaxed text-fg-muted'
const KBD = 'rounded-sm border border-line-strong px-1.5 py-0.5 font-mono text-[0.6875rem] text-fg-muted'
</script>

<template>
  <div class="h-full min-w-0 overflow-y-auto bg-surface">
    <div class="mx-auto flex w-full max-w-[1280px] flex-col gap-6 px-4 py-6 lg:px-10 lg:py-9">
      <header class="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
        <button
          v-if="navigation?.enabled.value"
          type="button"
          data-test="start-mobile-menu"
          class="flex h-9 w-8 shrink-0 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-fg-muted hover:bg-card hover:text-fg focus-visible:outline-2 focus-visible:outline-primary"
          aria-label="Abrir navegação"
          :aria-expanded="navigation.open.value"
          @click="navigation.toggle($event.currentTarget as HTMLElement)"
        >
          <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" /></svg>
        </button>
        <h1 class="m-0 min-w-0 grow text-2xl font-semibold tracking-tight">O que vamos resolver?</h1>
        <ClaudeAuthStatus />
        <RouterLink :class="[BTN, 'inline-flex items-center gap-2 no-underline']" to="/tarefas">
          Ver tarefas
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
        </RouterLink>
      </header>

      <form class="flex min-w-0 flex-col rounded-2xl border border-line-strong bg-panel" @submit.prevent="submit">
        <label class="block px-[18px] pt-4 pb-1.5">
          <span class="sr-only">Objetivo para o agente</span>
          <textarea
            v-model="goal"
            :disabled="busy"
            maxlength="6000"
            placeholder="Descreva um objetivo. O agente do topo organiza as tarefas e acompanha cada entrega."
            class="block min-h-[4.5rem] w-full resize-y border-0 bg-transparent p-0 text-[0.9375rem] leading-relaxed text-fg placeholder:text-fg-subtle focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-primary"
            aria-keyshortcuts="Control+Enter Meta+Enter"
            @keydown.ctrl.enter.exact.prevent="submit"
            @keydown.meta.enter.exact.prevent="submit"
          />
        </label>
        <p v-if="noTop" data-test="goal-no-top" class="m-0 px-[18px] pb-2 text-xs text-secondary-soft">
          Este projeto ainda não tem um CTO. Crie um na <RouterLink class="text-info-soft hover:underline focus-visible:outline-2 focus-visible:outline-primary" :to="{ name: 'agents', params: { projectId: selected } }">Organização</RouterLink>.
        </p>
        <div class="flex flex-wrap items-center gap-2 px-2.5 pt-2 pb-2.5 pl-4">
          <span class="mr-0.5 text-[0.78125rem] text-fg-muted">Projeto</span>
          <FilterChip
            v-for="project in chips"
            :key="project.id"
            data-test="goal-project"
            :data-id="project.id"
            :label="project.name"
            :pressed="selected === String(project.id)"
            @toggle="toggleProject(project.id)"
          >
            <template #icon><span class="size-2 shrink-0 rounded-[2px]" :style="{ backgroundColor: project.color }" /></template>
          </FilterChip>
          <span class="relative inline-flex">
            <select
              data-test="goal-project-other"
              aria-label="Projeto do objetivo"
              :disabled="busy"
              :value="''"
              class="h-[30px] cursor-pointer appearance-none rounded-full border border-line bg-transparent pr-7 pl-[11px] text-[0.78125rem] text-fg-muted hover:bg-card hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
              @change="pickOther"
            >
              <option value="">Outro…</option>
              <option v-for="project in projects.projects" :key="project.id" :value="String(project.id)" :disabled="!project.available">{{ project.name }}{{ !project.available ? ' (indisponível)' : '' }}</option>
            </select>
            <svg class="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2 text-fg-muted" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
          </span>
          <span class="flex-1" />
          <span data-test="goal-shortcut" class="hidden items-center gap-1 sm:flex" aria-hidden="true"><kbd :class="KBD">{{ submitKey }}</kbd><kbd :class="KBD">Enter</kbd></span>
          <button data-test="goal-submit" :class="[BTN_PRIMARY, 'ml-1.5']" :disabled="busy || !selected || !top || !goal.trim()" type="submit">
            {{ busy ? 'Entregando…' : `Entregar a ${top?.name ?? 'um agente'}` }}
          </button>
        </div>
        <p v-if="error" :class="[ERROR, 'px-[18px] pb-3']" role="alert">{{ error }}</p>
      </form>

      <div class="grid min-w-0 items-start gap-x-9 gap-y-8 lg:grid-cols-3">
        <section data-test="start-with-you" aria-labelledby="with-you-title" :class="SECTION">
          <div :class="SECTION_HEAD">
            <h2 id="with-you-title" :class="SECTION_TITLE">Com você</h2>
            <span v-if="withYouText" :class="SECTION_COUNT">{{ withYouText }}</span>
          </div>
          <RouterLink
            v-if="unreadTotal"
            to="/inbox?aba=novidades"
            data-test="start-notices"
            class="flex min-w-0 items-start gap-2.5 border-b border-line px-1 py-2.5 text-fg no-underline hover:bg-panel focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          >
            <svg class="mt-1.5 shrink-0 stroke-secondary" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3 2 20h20L12 3z" /><path d="M12 10v4M12 17v.01" /></svg>
            <span class="flex min-w-0 grow flex-col gap-0.5">
              <span class="text-sm font-medium text-secondary-soft">{{ unreadTotal }} {{ unreadTotal === 1 ? 'novidade' : 'novidades' }} {{ unreadTotal === 1 ? 'de agente' : 'dos agentes' }}</span>
              <span class="flex min-w-0 items-center gap-2 text-xs text-fg-muted">
                <span class="min-w-0 truncate">{{ unreadText }}</span>
                <span class="flex-1" />
                <span class="shrink-0 text-info-soft">Abrir a Inbox</span>
              </span>
            </span>
          </RouterLink>
          <div v-if="org.decisionsPending.length" class="flex min-w-0 flex-col gap-2 border-b border-line py-3">
            <DecisionCard v-for="decision in org.decisionsPending" :key="decision.id" :decision="decision" />
          </div>
          <StartSessionRow v-for="session in waiting.slice(0, COLUMN_ROWS)" :key="session.session_id" data-test="start-waiting" :session="session" />
          <RouterLink v-if="waiting.length > COLUMN_ROWS" data-test="start-waiting-more" to="/sessions?estado=sua-vez" :class="[LINK, 'pt-3']">Mais {{ waiting.length - COLUMN_ROWS }} {{ waiting.length - COLUMN_ROWS === 1 ? 'conversa' : 'conversas' }}</RouterLink>
          <p v-if="!waiting.length && !unreadTotal && !org.decisionsPending.length" :class="EMPTY">Nada espera você agora.</p>
        </section>

        <section data-test="start-running-section" aria-labelledby="running-title" :class="SECTION">
          <div :class="SECTION_HEAD">
            <h2 id="running-title" :class="SECTION_TITLE">Em andamento</h2>
            <span v-if="running.length" :class="SECTION_COUNT">{{ running.length }}</span>
            <span class="flex-1" />
            <RouterLink to="/dashboard" :class="LINK">Ver no Painel</RouterLink>
          </div>
          <StartSessionRow v-for="session in running.slice(0, COLUMN_ROWS)" :key="session.session_id" data-test="start-running" :session="session" />
          <RouterLink v-if="running.length > COLUMN_ROWS" data-test="start-running-more" to="/dashboard" :class="[LINK, 'pt-3']">Mais {{ running.length - COLUMN_ROWS }} em andamento</RouterLink>
          <p v-if="!running.length" :class="EMPTY">Nenhuma conversa em execução.</p>
        </section>

        <section data-test="start-delivered-section" aria-labelledby="delivered-title" :class="SECTION">
          <div :class="SECTION_HEAD">
            <h2 id="delivered-title" :class="SECTION_TITLE">Entregue hoje</h2>
            <span v-if="deliveredText" :class="SECTION_COUNT">{{ deliveredText }}</span>
            <span class="flex-1" />
            <RouterLink to="/entregas" :class="LINK">Ver em Entregas</RouterLink>
          </div>
          <div v-if="deliveries.error" data-test="start-deliveries-error" :class="[ERROR, 'flex flex-wrap items-center gap-2 py-3']" role="alert">
            <span class="min-w-0">Não foi possível carregar as entregas. {{ deliveries.error }}</span>
            <button type="button" data-test="start-deliveries-retry" :class="BTN" @click="reloadDeliveries">Tentar novamente</button>
          </div>
          <div v-else-if="delivered === null" role="status" class="grid gap-3 py-4">
            <span class="sr-only">Carregando as entregas…</span>
            <span class="block h-4 max-w-[80%] rounded bg-panel" /><span class="block h-4 max-w-[65%] rounded bg-panel" /><span class="block h-4 max-w-[80%] rounded bg-panel" />
          </div>
          <template v-else>
            <component
              :is="d.session_id ? RouterLink : 'div'"
              v-for="d in deliveredShown"
              :key="d.id"
              v-bind="d.session_id ? { to: { name: 'session', params: { id: d.session_id } } } : {}"
              data-test="start-delivered"
              class="flex min-w-0 items-start gap-2.5 border-b border-line px-1 py-2.5 text-fg no-underline"
              :class="d.session_id ? 'hover:bg-panel focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary' : ''"
            >
              <span class="mt-[0.1875rem] w-[2.375rem] shrink-0 font-mono text-[0.71875rem] text-fg-subtle tabular-nums">{{ formatTime(d.finished_at) }}</span>
              <span class="flex min-w-0 grow flex-col gap-1">
                <span class="line-clamp-2 text-[0.84375rem] leading-5 [overflow-wrap:anywhere]">{{ deliveryTitle(d) }}</span>
                <span class="flex min-w-0 items-center gap-1.5 text-xs text-fg-muted">
                  <span class="size-2 shrink-0 rounded-[2px]" :style="{ backgroundColor: (d.project_id === null ? undefined : projects.byId(d.project_id))?.color ?? 'var(--color-fg-subtle)' }" />
                  <span class="truncate">{{ d.project_name }}</span>
                </span>
              </span>
            </component>
            <RouterLink v-if="delivered.length > DELIVERED_ROWS" data-test="start-delivered-more" to="/entregas" :class="[LINK, 'pt-3']">Mais {{ delivered.length - DELIVERED_ROWS }} {{ delivered.length - DELIVERED_ROWS === 1 ? 'entrega' : 'entregas' }} de hoje</RouterLink>
            <p v-if="!delivered.length" :class="EMPTY">Nada entregue hoje ainda.</p>
          </template>
        </section>
      </div>
    </div>
  </div>
</template>
