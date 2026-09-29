<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import ActivityChart from '../components/dashboard/ActivityChart.vue'
import NowCard from '../components/dashboard/NowCard.vue'
import ConversationRow from '../components/conversation/ConversationRow.vue'
import DisplayStateIcon from '../components/DisplayStateIcon.vue'
import BranchLabel from '../components/git/BranchLabel.vue'
import { getActivity } from '../api/http'
import { changedCount, repoLabel, useGitStore } from '../stores/git'
import { useProjectsStore } from '../stores/projects'
import { useSessionsStore } from '../stores/sessions'
import type { ActivityDay } from '../types/api'

const sessions = useSessionsStore()
const projects = useProjectsStore()
const git = useGitStore()

const active = computed(() => sessions.all.filter((s) => s.display_state === 'running' || s.display_state === 'waiting'))
const running = computed(() => active.value.filter((s) => s.display_state === 'running').length)
const waiting = computed(() => active.value.filter((s) => s.display_state === 'waiting').length)
const startOfToday = () => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() / 1000 }
const finishedToday = computed(() => sessions.all.filter((s) => (s.finished_at ?? 0) >= startOfToday()).length)
const changedFiles = (projectId: number) => git.reposFor(projectId).reduce((sum, r) => sum + changedCount(r), 0)
const projectsWithChanges = computed(() => projects.projects.filter((p) => changedFiles(p.id) > 0).length)
const waitingIn = (projectId: number) => sessions.forProject(projectId).filter((s) => s.display_state === 'waiting').length
const recent = computed(() => sessions.all.slice(0, 8))

const activity = ref<ActivityDay[]>([])
const activityError = ref(false)
const activityLoading = ref(false)
async function loadActivity() {
  activityLoading.value = true
  activityError.value = false
  try {
    activity.value = await getActivity(14)
  } catch {
    activityError.value = true
  } finally {
    activityLoading.value = false
  }
}
onMounted(() => {
  projects.projects.forEach((p) => git.ensure(p.id))
  void loadActivity()
})

function scrollToProjects() {
  document.getElementById('dashboard-projetos')?.scrollIntoView({ block: 'start' })
}
</script>

<template>
  <div class="mx-auto flex w-full max-w-6xl flex-col gap-8 px-6 py-6">
    <h1 class="m-0 font-mono text-sm tracking-[0.08em] text-fg uppercase">Dashboard</h1>

    <section aria-labelledby="now-title" class="flex flex-col gap-3">
      <h2 id="now-title" class="m-0 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Agora</h2>
      <p v-if="active.length === 0" data-test="now-empty" class="m-0 text-fg-muted">Nenhuma conversa ativa agora.</p>
      <div v-else class="grid gap-3 md:grid-cols-2">
        <NowCard v-for="s in active" :key="s.session_id" :session="s" :project="projects.byId(s.project_id)" />
      </div>
    </section>

    <section aria-label="Números" class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <RouterLink data-test="stat-running" to="/inbox?aba=em-execucao" class="flex flex-col rounded-lg border border-line p-4 no-underline hover:bg-card"><span class="text-3xl font-semibold text-fg">{{ running }}</span><span class="text-sm text-fg-muted">Em execução</span></RouterLink>
      <RouterLink data-test="stat-waiting" to="/inbox?aba=pede-voce" class="flex flex-col rounded-lg border border-line p-4 no-underline hover:bg-card"><span class="text-3xl font-semibold text-fg">{{ waiting }}</span><span class="text-sm text-fg-muted">Aguardando você</span></RouterLink>
      <RouterLink data-test="stat-finished-today" to="/sessions?estado=finalizadas" class="flex flex-col rounded-lg border border-line p-4 no-underline hover:bg-card"><span class="text-3xl font-semibold text-fg">{{ finishedToday }}</span><span class="text-sm text-fg-muted">Finalizadas hoje</span></RouterLink>
      <button type="button" data-test="stat-projects-changes" class="flex flex-col rounded-lg border border-line p-4 text-left hover:bg-card" @click="scrollToProjects"><span class="text-3xl font-semibold text-fg">{{ projectsWithChanges }}</span><span class="text-sm text-fg-muted">Projetos com alterações</span></button>
    </section>

    <section class="rounded-lg border border-line p-4">
      <div v-if="activityError" class="flex flex-col items-start gap-2">
        <p data-test="activity-error" role="alert" class="m-0 text-sm text-secondary-soft">Não foi possível carregar a atividade.</p>
        <button type="button" data-test="activity-retry" class="h-8 rounded-md border border-line-strong px-2.5 text-xs text-fg hover:bg-card" @click="loadActivity">Tentar de novo</button>
      </div>
      <p v-else-if="activityLoading && activity.length === 0" class="m-0 text-sm text-fg-muted">Carregando…</p>
      <ActivityChart v-else :data="activity" :projects="projects.projects" :days="14" :today="new Date()" />
    </section>

    <div class="grid gap-6 lg:grid-cols-2">
      <section data-test="recent-list" aria-labelledby="recent-title" class="flex flex-col gap-2">
        <h2 id="recent-title" class="m-0 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Conversas recentes</h2>
        <ConversationRow v-for="s in recent" :key="s.session_id" :session="s" variant="compact" />
      </section>
      <section id="dashboard-projetos" data-test="projects-list" aria-labelledby="projects-title" class="flex flex-col gap-2">
        <h2 id="projects-title" class="m-0 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Projetos</h2>
        <RouterLink v-for="p in projects.projects" :key="p.id" :to="{ name: 'project', params: { id: p.id } }" class="flex min-h-11 items-center gap-3 rounded-md px-2 text-fg no-underline hover:bg-card">
          <span class="size-2.5 rounded-[3px]" :style="{ backgroundColor: p.color }" />
          <span class="min-w-0 grow truncate">{{ p.name }}</span>
          <BranchLabel v-if="git.reposFor(p.id)[0]" :text="repoLabel(git.reposFor(p.id)[0]!)" muted />
          <span class="text-xs text-fg-muted">{{ changedFiles(p.id) }} {{ changedFiles(p.id) === 1 ? 'arquivo' : 'arquivos' }}</span>
          <span v-if="waitingIn(p.id)" class="flex items-center gap-1 text-xs text-secondary"><DisplayStateIcon display="waiting" :size="11" />{{ waitingIn(p.id) }}</span>
        </RouterLink>
      </section>
    </div>
  </div>
</template>
