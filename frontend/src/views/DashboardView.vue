<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import NowRow from '../components/dashboard/NowRow.vue'
import LoadStatus from '../components/LoadStatus.vue'
import DisplayStateIcon from '../components/DisplayStateIcon.vue'
import ProjectTag from '../components/conversation/ProjectTag.vue'
import { formatReset, resetPhrase, severityClass } from '../components/sidebar/usageFormat'
import { isDiscarded, markLane } from '../conversation/marks'
import { needsYou } from '../conversation/needsYou'
import { formatActivity } from '../format'
import { useLoadState } from '../loadState'
import { useMinuteClock } from '../minuteClock'
import { changedCount, repoLabel, useGitStore } from '../stores/git'
import { useProjectsStore } from '../stores/projects'
import { useSessionsStore } from '../stores/sessions'
import { useUsageStore } from '../stores/usage'
import type { Session } from '../types/api'

const sessions = useSessionsStore()
const projects = useProjectsStore()
const git = useGitStore()
const usage = useUsageStore()
const loadState = useLoadState()
const clock = useMinuteClock()

const NOW_LIMIT = 6
const FINISHED_LIMIT = 8
const CHANGES_LIMIT = 4

// Weekly subscription limit, beside the title. Without it there is nothing to show (plan included).
const weekly = computed(() => usage.weekly)
const weeklyReset = computed(() => (weekly.value ? formatReset(weekly.value.resets_at, clock.value) : ''))
const weeklyText = computed(() => (weekly.value ? `${weekly.value.percent}%${weeklyReset.value ? ` · renova ${resetPhrase(weeklyReset.value)}` : ''}` : ''))
const weeklyLabel = computed(() => (weekly.value ? `Semana: ${weekly.value.percent}%${weeklyReset.value ? `, renova ${resetPhrase(weeklyReset.value)}` : ''}` : ''))

// Only what is for now or for review gets a row; sessions on hold or blocked stay out.
const active = computed(() => sessions.all.filter((s) => (s.display_state === 'running' || s.display_state === 'waiting') && markLane(s) !== 'later' && !isDiscarded(s)))
// Pending requests first, then running, then the rest of the waiting ones; newest first inside each group.
const nowRank = (s: Session) => (s.awaiting_decision || s.pending_kind != null ? 0 : s.display_state === 'running' ? 1 : 2)
const nowRows = computed(() =>
  [...active.value]
    .sort((a, b) => nowRank(a) - nowRank(b) || b.last_activity_at - a.last_activity_at)
    .slice(0, NOW_LIMIT),
)
// "Running" is a fact, not a queue: it counts the ones on hold too.
const running = computed(() => sessions.all.filter((s) => s.display_state === 'running' && !isDiscarded(s)).length)
// Only the waits that need you count, the same rule as the sidebar.
const isWaitingOnYou = (s: Session) => s.display_state === 'waiting' && needsYou(s) && markLane(s) === 'now'
const waiting = computed(() => active.value.filter(isWaitingOnYou).length)
const toReview = computed(() => sessions.all.filter((s) => s.display_state !== 'finished' && markLane(s) === 'review').length)

const startOfToday = () => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() / 1000 }
const finishedToday = computed(() => {
  const since = startOfToday()
  return sessions.all.filter((s) => s.finished && (s.finished_at ?? 0) >= since).sort((a, b) => (b.finished_at ?? 0) - (a.finished_at ?? 0))
})

const changedFiles = (projectId: number) => git.reposFor(projectId).reduce((sum, r) => sum + changedCount(r), 0)
// The projects that have changes, the biggest first; the ones git has not answered for yet are not "without changes".
const changed = computed(() =>
  projects.regular
    .map((project, index) => ({ project, index, files: changedFiles(project.id) }))
    .filter((p) => p.files > 0)
    .sort((a, b) => b.files - a.files || a.index - b.index),
)
const changedShown = computed(() => changed.value.slice(0, CHANGES_LIMIT))
const biggest = computed(() => changed.value[0]?.files ?? 1)
const hiddenChanged = computed(() => changed.value.length - changedShown.value.length)
const clean = computed(() => projects.regular.filter((p) => git.isLoaded(p.id) && changedFiles(p.id) === 0).length)
const changesMore = computed(() => {
  const parts: string[] = []
  if (hiddenChanged.value > 0) parts.push(`Mais ${hiddenChanged.value} com alterações`)
  if (clean.value > 0) parts.push(clean.value === 1 ? '1 projeto sem alterações fica fora da lista' : `${clean.value} projetos sem alterações ficam fora da lista`)
  return parts.join(' · ')
})

onMounted(() => projects.regular.forEach((p) => git.ensure(p.id)))

function scrollToChanges() {
  document.getElementById('dashboard-alteracoes')?.scrollIntoView({ block: 'start' })
}

const STAT = 'flex min-w-0 flex-col gap-0.5 px-5 py-3 text-left no-underline first:pl-0 hover:bg-panel focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary lg:border-l lg:border-line lg:first:border-l-0'
const STAT_NUMBER = 'text-[1.75rem] leading-[1.15] font-semibold tracking-tight tabular-nums'
const STAT_LABEL = 'flex items-center gap-1.5 text-[0.78125rem] text-fg-muted'
const SECTION_HEAD = 'flex h-[34px] items-center gap-2 border-b border-line-strong'
const SECTION_TITLE = 'm-0 text-[0.9375rem] font-semibold tracking-tight'
const SECTION_COUNT = 'font-mono text-[0.71875rem] text-fg-subtle tabular-nums'
const LINK = 'text-[0.8125rem] whitespace-nowrap text-info-soft no-underline hover:text-fg hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary'
const EMPTY = 'm-0 border-b border-line py-6 text-[0.8125rem] leading-relaxed text-fg-muted'
const ROW = 'group relative flex min-h-[2.125rem] items-center gap-2.5 border-b border-line text-[0.84375rem] text-fg no-underline hover:bg-panel focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary'
const TIME = 'w-[3.875rem] shrink-0 text-right font-mono text-[0.71875rem] text-fg-subtle tabular-nums whitespace-nowrap'
</script>

<template>
  <div class="mx-auto flex w-full max-w-6xl flex-col gap-6 px-6 py-6 md:px-12 md:py-9">
    <div class="flex flex-wrap items-center gap-x-3 gap-y-2">
      <h1 class="m-0 text-2xl font-semibold tracking-tight text-fg">Painel</h1>
      <span class="flex-1" />
      <template v-if="weekly">
        <div
          data-test="dashboard-usage"
          role="meter"
          aria-valuemin="0"
          aria-valuemax="100"
          :aria-valuenow="weekly.percent"
          :aria-label="weeklyLabel"
          class="flex items-center gap-3"
          :class="{ 'opacity-60': usage.snapshot?.error }"
        >
          <span class="text-[0.78125rem] text-fg-muted">Semana</span>
          <span class="h-1.5 w-[7.5rem] overflow-hidden rounded-full bg-elevated"><span class="block h-full rounded-full" :class="severityClass(weekly.severity)" :style="{ width: `${weekly.percent}%` }" /></span>
          <span class="font-mono text-[0.71875rem] text-fg-subtle tabular-nums whitespace-nowrap">{{ weeklyText }}</span>
        </div>
        <span v-if="usage.snapshot?.plan" data-test="dashboard-plan" class="rounded-sm border border-line-strong px-1.5 py-0.5 font-mono text-[0.6875rem] text-fg-muted">{{ usage.snapshot.plan }}</span>
      </template>
    </div>

    <LoadStatus v-if="loadState !== 'ready'" :state="loadState" />

    <template v-if="loadState === 'ready'">
      <section aria-label="Números" class="grid grid-cols-2 border-y border-line sm:grid-cols-3 lg:grid-cols-5">
        <RouterLink data-test="stat-running" to="/inbox?aba=em-execucao" :class="STAT">
          <span :class="[STAT_NUMBER, running === 0 ? 'text-fg-subtle' : 'text-fg']">{{ running }}</span>
          <span :class="STAT_LABEL"><DisplayStateIcon display="running" :size="12" />Em execução</span>
        </RouterLink>
        <RouterLink data-test="stat-waiting" to="/inbox?aba=pede-voce" :class="STAT">
          <span :class="[STAT_NUMBER, waiting === 0 ? 'text-fg-subtle' : 'text-fg']">{{ waiting }}</span>
          <span :class="STAT_LABEL"><DisplayStateIcon display="waiting" :size="12" :quiet="waiting === 0" />Aguardando você</span>
        </RouterLink>
        <RouterLink data-test="stat-review" to="/inbox?aba=para-revisar" :class="STAT">
          <span :class="[STAT_NUMBER, toReview === 0 ? 'text-fg-subtle' : 'text-fg']">{{ toReview }}</span>
          <span :class="STAT_LABEL">Para revisar</span>
        </RouterLink>
        <RouterLink data-test="stat-finished-today" to="/entregas" :class="STAT">
          <span :class="[STAT_NUMBER, finishedToday.length === 0 ? 'text-fg-subtle' : 'text-fg']">{{ finishedToday.length }}</span>
          <span :class="STAT_LABEL"><DisplayStateIcon display="finished" :size="12" />Finalizadas hoje</span>
        </RouterLink>
        <button type="button" data-test="stat-projects-changes" :class="STAT" @click="scrollToChanges">
          <span :class="[STAT_NUMBER, changed.length === 0 ? 'text-fg-subtle' : 'text-fg']">{{ changed.length }}</span>
          <span :class="STAT_LABEL">Projetos com alterações</span>
        </button>
      </section>

      <section aria-labelledby="now-title" class="flex min-w-0 flex-col">
        <div :class="SECTION_HEAD">
          <h2 id="now-title" :class="SECTION_TITLE">Agora</h2>
          <span v-if="running" data-test="now-running-count" :class="SECTION_COUNT">{{ running }} em execução</span>
          <span class="flex-1" />
          <RouterLink v-if="active.length > NOW_LIMIT" data-test="now-more" to="/inbox?aba=todas" :class="LINK">Ver as {{ active.length }} na Inbox</RouterLink>
        </div>
        <p v-if="active.length === 0" data-test="now-empty" :class="EMPTY">Nenhuma conversa ativa agora.</p>
        <NowRow v-for="s in nowRows" :key="s.session_id" :session="s" />
      </section>

      <div class="grid min-w-0 items-start gap-x-11 gap-y-8 lg:grid-cols-2">
        <section data-test="finished-today" aria-labelledby="finished-title" class="flex min-w-0 flex-col">
          <div :class="SECTION_HEAD">
            <h2 id="finished-title" :class="SECTION_TITLE">Finalizadas hoje</h2>
            <span v-if="finishedToday.length" :class="SECTION_COUNT">{{ finishedToday.length }}</span>
          </div>
          <p v-if="finishedToday.length === 0" :class="EMPTY">Nada finalizado hoje ainda.</p>
          <div v-for="s in finishedToday.slice(0, FINISHED_LIMIT)" :key="s.session_id" data-test="finished-row" :class="ROW">
            <DisplayStateIcon display="finished" :size="13" />
            <RouterLink
              data-test="finished-row-link"
              :to="{ name: 'session', params: { id: s.session_id } }"
              class="min-w-0 grow truncate no-underline after:absolute after:inset-0 focus-visible:outline-none focus-visible:after:ring-2 focus-visible:after:ring-primary focus-visible:after:ring-inset"
              :class="s.unread ? 'font-medium text-fg' : 'text-fg'"
            >{{ s.title }}</RouterLink>
            <ProjectTag class="max-w-[40%] shrink-0" :project-id="s.project_id" />
            <span :class="TIME">{{ formatActivity(s.finished_at ?? s.last_activity_at) }}</span>
          </div>
          <RouterLink v-if="finishedToday.length > FINISHED_LIMIT" data-test="finished-more" to="/entregas" :class="[LINK, 'pt-3']">Mais {{ finishedToday.length - FINISHED_LIMIT }} em Entregas</RouterLink>
        </section>

        <section id="dashboard-alteracoes" data-test="changes-list" aria-labelledby="changes-title" class="flex min-w-0 flex-col">
          <div :class="SECTION_HEAD">
            <h2 id="changes-title" :class="SECTION_TITLE">Projetos com alterações</h2>
            <span v-if="changed.length" :class="SECTION_COUNT">{{ changed.length }}</span>
          </div>
          <p v-if="changed.length === 0" :class="EMPTY">Nenhum projeto com alterações.</p>
          <RouterLink
            v-for="{ project, files } in changedShown"
            :key="project.id"
            data-test="changes-row"
            :to="{ name: 'project', params: { id: project.id }, query: { visao: 'git' } }"
            :class="[ROW, 'min-h-[2.125rem]']"
          >
            <span class="size-2 shrink-0 rounded-[2px]" :style="{ backgroundColor: project.color }" />
            <span class="shrink-0 font-medium">{{ project.name }}</span>
            <span class="min-w-0 grow truncate font-mono text-[0.71875rem] text-fg-subtle">{{ git.reposFor(project.id)[0] ? repoLabel(git.reposFor(project.id)[0]!) : '' }}</span>
            <span class="h-1 w-16 shrink-0 overflow-hidden rounded-full bg-elevated" aria-hidden="true"><span data-test="changes-bar" class="block h-full rounded-full bg-fg-muted" :style="{ width: `${Math.round((files / biggest) * 100)}%` }" /></span>
            <span class="w-[4.75rem] shrink-0 text-right font-mono text-[0.71875rem] text-fg-subtle tabular-nums">{{ files }} {{ files === 1 ? 'arquivo' : 'arquivos' }}</span>
          </RouterLink>
          <p v-if="changesMore" data-test="changes-more" class="m-0 pt-3 text-[0.78125rem] text-fg-subtle">{{ changesMore }}</p>
        </section>
      </div>
    </template>
  </div>
</template>
