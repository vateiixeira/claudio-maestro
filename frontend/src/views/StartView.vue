<script setup lang="ts">
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { errorMessage, sendMessage } from '../api/http'
import { AGENTS_NAVIGATION_KEY } from '../agentsNavigation'
import { useOrgStore } from '../stores/org'
import { useProjectsStore } from '../stores/projects'
import { useSessionsStore } from '../stores/sessions'
import { useTasksStore } from '../stores/tasks'
import { needsYou } from '../conversation/needsYou'
import { isDiscarded } from '../conversation/marks'
import { goalDrafts } from '../workGoal'
import type { Task, TaskStatus } from '../types/org'
import DecisionCard from '../components/org/tasks/DecisionCard.vue'
import StartTaskRow from '../components/start/StartTaskRow.vue'
import { BTN, BTN_PRIMARY, ERROR } from '../components/org/styles'

const ACTIVE: TaskStatus[] = ['in_progress', 'in_review', 'blocked']
const ACTIVE_SHOWN = 8
const RECENT_SHOWN = 5

const org = useOrgStore()
const tasks = useTasksStore()
const projects = useProjectsStore()
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

const busy = ref(false)
const error = ref('')
const loading = ref(true)
const loadError = ref('')
const active = ref<Task[]>([])
const recent = ref<Task[]>([])

const waitingSessions = computed(() => useSessionsStore().all.filter((s) => s.display_state === 'waiting' && needsYou(s) && !isDiscarded(s)))
const needCount = computed(() => org.decisionsPending.length + waitingSessions.value.length)

let ticket = 0
let alive = true
async function load() {
  const mine = ++ticket
  loadError.value = ''
  loading.value = true
  const [open, done] = await Promise.allSettled([
    tasks.list({ status: ACTIVE, limit: ACTIVE_SHOWN, order: 'recent' }),
    tasks.list({ status: 'done', limit: RECENT_SHOWN, order: 'recent' }),
  ])
  if (mine !== ticket) return
  if (open.status === 'fulfilled') active.value = open.value
  if (done.status === 'fulfilled') recent.value = done.value
  const failed = [open, done].find((r) => r.status === 'rejected')
  if (failed?.status === 'rejected') loadError.value = errorMessage(failed.reason)
  loading.value = false
}
watch(() => tasks.version, () => { void load() })
void load()
onBeforeUnmount(() => { ticket++; alive = false })

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

const SECTION_TITLE = 'm-0 text-[0.9375rem] font-medium'
</script>

<template>
  <div class="h-full min-w-0 overflow-y-auto bg-surface">
    <div class="mx-auto flex w-full max-w-[1100px] flex-col gap-6 px-4 py-6 lg:px-8">
      <header class="flex min-w-0 items-center gap-3">
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
        <div class="min-w-0 grow">
          <p class="m-0 mb-1 text-[0.6875rem] text-fg-subtle">Cláudio Maestro</p>
          <h1 class="m-0 text-2xl font-semibold tracking-tight">O que vamos resolver?</h1>
        </div>
        <RouterLink :class="[BTN, 'inline-flex items-center no-underline']" to="/tarefas">Ver tarefas →</RouterLink>
      </header>

      <form class="flex max-w-[900px] flex-col gap-3 rounded-[9px] border border-line-strong bg-panel px-4 pt-4 pb-3.5" @submit.prevent="submit">
        <label>
          <span class="sr-only">Objetivo para o agente</span>
          <textarea
            v-model="goal"
            :disabled="busy"
            maxlength="6000"
            placeholder="Descreva um objetivo. O agente do topo organiza as tarefas e acompanha cada entrega."
            class="min-h-[90px] w-full resize-y border-0 bg-transparent p-0 text-sm leading-[1.8] text-fg placeholder:text-fg-subtle focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-primary"
          />
        </label>
        <p v-if="noTop" data-test="goal-no-top" class="m-0 text-xs text-secondary-soft">
          Este projeto ainda não tem um CTO. Crie um na <RouterLink class="text-info-soft hover:underline focus-visible:outline-2 focus-visible:outline-primary" :to="{ name: 'agents', params: { projectId: selected } }">Organização</RouterLink>.
        </p>
        <div class="flex flex-wrap items-center justify-between gap-3">
          <label class="flex min-w-0 items-center gap-2.5 text-[0.6875rem] text-fg-subtle">
            Projeto
            <select v-model="selected" :disabled="busy" aria-label="Projeto do objetivo" class="h-8 min-w-0 max-w-60 rounded-md border border-line-strong bg-surface px-2 text-xs text-fg focus-visible:outline-2 focus-visible:outline-primary">
              <option value="">Escolher projeto</option>
              <option v-for="project in projects.projects" :key="project.id" :value="String(project.id)" :disabled="!project.available">{{ project.name }}{{ !project.available ? ' (indisponível)' : '' }}</option>
            </select>
          </label>
          <button data-test="goal-submit" :class="BTN_PRIMARY" :disabled="busy || !selected || !top || !goal.trim()" type="submit">
            {{ busy ? 'Entregando…' : `Entregar a ${top?.name ?? 'um agente'}` }} <span aria-hidden="true">↗</span>
          </button>
        </div>
        <p v-if="error" :class="ERROR" role="alert">{{ error }}</p>
      </form>

      <p v-if="loadError" data-test="start-error" :class="ERROR" role="alert">
        Não foi possível atualizar toda a visão geral. {{ loadError }}
        <button type="button" data-test="start-retry" :class="BTN" @click="load">Tentar novamente</button>
      </p>

      <div v-if="loading && !active.length && !recent.length" role="status" class="grid gap-4 py-4">
        <span class="sr-only">Carregando o trabalho…</span>
        <span class="block h-[18px] max-w-[80%] rounded bg-panel" /><span class="block h-[18px] max-w-[65%] rounded bg-panel" /><span class="block h-[18px] max-w-[80%] rounded bg-panel" />
      </div>
      <template v-else>
        <section v-if="needCount" aria-labelledby="need-you-title" class="flex min-w-0 flex-col gap-2">
          <h2 id="need-you-title" :class="SECTION_TITLE">Precisam de você <span class="text-xs font-normal text-fg-subtle">{{ needCount }}</span></h2>
          <DecisionCard v-for="decision in org.decisionsPending" :key="decision.id" :decision="decision" />
          <RouterLink
            v-for="session in waitingSessions"
            :key="session.session_id"
            :to="`/sessions/${session.session_id}`"
            data-test="start-waiting"
            class="flex min-w-0 items-center justify-between gap-3 border-t border-line px-1 py-3 text-[0.8125rem] text-fg no-underline hover:bg-panel focus-visible:outline-2 focus-visible:outline-primary"
          >
            <span class="min-w-0 [overflow-wrap:anywhere]">{{ session.title || 'Conversa sem título' }}<span class="ml-3 text-[0.6875rem] text-fg-subtle">{{ projects.byId(session.project_id)?.name }}</span></span>
            <span class="shrink-0 text-[0.6875rem] text-secondary-soft"><span aria-hidden="true">△ </span>Responder ao pedido</span>
          </RouterLink>
        </section>

        <div class="grid min-w-0 gap-x-10 gap-y-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
          <section aria-labelledby="active-title" class="flex min-w-0 flex-col">
            <div class="mb-2 flex items-baseline justify-between gap-3">
              <h2 id="active-title" :class="SECTION_TITLE">Em andamento</h2>
              <RouterLink class="text-xs text-info-soft hover:underline focus-visible:outline-2 focus-visible:outline-primary" to="/tarefas">Ver todas</RouterLink>
            </div>
            <StartTaskRow v-for="task in active" :key="task.id" :task="task" />
            <div v-if="!active.length && !loadError" class="border-t border-line py-8 text-[0.8125rem] leading-[1.8] text-fg-muted">
              <strong class="mb-1 block text-[0.9375rem] font-medium text-fg">O próximo passo começa com um objetivo</strong>
              Escolha o projeto acima e conte ao agente do topo o que precisa resolver.
            </div>
          </section>
          <section aria-labelledby="recent-title" class="flex min-w-0 flex-col">
            <div class="mb-2 flex items-baseline justify-between gap-3">
              <h2 id="recent-title" :class="SECTION_TITLE">Concluídas recentes</h2>
            </div>
            <StartTaskRow v-for="task in recent" :key="task.id" :task="task" />
            <div v-if="!recent.length && !loadError" class="border-t border-line py-8 text-[0.8125rem] leading-[1.8] text-fg-muted">As tarefas concluídas aparecem aqui.</div>
          </section>
        </div>
      </template>
    </div>
  </div>
</template>
