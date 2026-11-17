<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import OrgPage from '../components/org/OrgPage.vue'
import DisplayStateIcon from '../components/DisplayStateIcon.vue'
import GroupHeader from '../components/ui/GroupHeader.vue'
import MoreMenu, { type MoreMenuItem } from '../components/ui/MoreMenu.vue'
import { errorMessage } from '../api/http'
import { isDiscarded } from '../conversation/marks'
import { useMinuteClock } from '../minuteClock'
import { activityText, isActiveToday, shortPath, staleDays } from '../projectsList'
import { changedCount, repoLabel, useGitStore } from '../stores/git'
import { useSessionsStore } from '../stores/sessions'
import { useProjectsStore } from '../stores/projects'
import type { Project } from '../types/api'

const projects = useProjectsStore()
const sessions = useSessionsStore()
const git = useGitStore()
const clock = useMinuteClock()
const now = computed(() => Math.floor(clock.value / 1000))
const query = ref('')
const searchInput = ref<HTMLInputElement | null>(null)
const visibleProjects = computed(() => {
  const term = query.value.trim().toLocaleLowerCase('pt-BR')
  return projects.regular.filter(p => `${p.name} ${p.path}`.toLocaleLowerCase('pt-BR').includes(term))
})
const activity = computed(() => Object.fromEntries(projects.regular.map(project => {
  const list = sessions.forProject(project.id).filter(session => !isDiscarded(session))
  const running = list.filter(s => s.display_state === 'running').length
  const open = list.filter(s => s.display_state !== 'finished').length
  const latest = Math.max(0, ...list.map(s => s.last_activity_at))
  return [project.id, { running, open, latest }]
})))
const noActivity = { running: 0, open: 0, latest: 0 }
const activityOf = (project: Project) => activity.value[project.id] ?? noActivity

// Newest activity first inside each group; "active today" also counts open conversations.
const groups = computed(() => {
  const byRecent = [...visibleProjects.value].sort((a, b) => activityOf(b).latest - activityOf(a).latest)
  const active = byRecent.filter(p => isActiveToday(activityOf(p).latest, activityOf(p).open, now.value))
  const idle = byRecent.filter(p => !active.includes(p))
  return [
    { key: 'active', title: 'Ativos hoje', projects: active },
    { key: 'idle', title: 'Parados', projects: idle },
  ].filter(group => group.projects.length)
})

// Folders that are gone have no repository to read; the rest loads once, like the Painel.
watch(() => projects.regular.map(p => `${p.id}:${p.available}`).join(), () => {
  projects.regular.filter(p => p.available).forEach(p => git.ensure(p.id))
}, { immediate: true })

const rootRepo = (project: Project) => {
  const repos = git.reposFor(project.id)
  return repos.find(r => r.rel_path === '.') ?? repos[0]
}
const branchOf = (project: Project) => {
  const repo = project.available ? rootRepo(project) : undefined
  return repo ? repoLabel(repo) : ''
}
const changedOf = (project: Project) => git.reposFor(project.id).reduce((sum, r) => sum + changedCount(r), 0)
const hasRepos = (project: Project) => project.available && git.reposFor(project.id).length > 0
const staleOf = (project: Project) => staleDays(changedOf(project), activityOf(project).latest, now.value)
function changesText(project: Project): string {
  if (!hasRepos(project)) return ''
  const changed = changedOf(project)
  if (!changed) return 'limpo'
  const stale = staleOf(project)
  if (stale !== null) return `${changed} há ${stale} dias`
  return `${changed} ${changed === 1 ? 'arquivo' : 'arquivos'}`
}
function openText(open: number): string {
  return `${open} ${open === 1 ? 'aberta' : 'abertas'}`
}

const actionItems: MoreMenuItem[] = [{ id: 'rename', label: 'Renomear' }]
function onAction(project: Project, id: string) {
  if (id === 'rename') void startRename(project)
}

const ROW = 'grid grid-cols-[8px_minmax(0,1fr)_180px_190px_100px_84px_28px] items-center gap-x-4 px-2.5'
const editing = ref<number | null>(null)
const name = ref('')
const saving = ref(false)
const retrying = ref(false)
const error = ref('')
const notice = ref('')
const input = ref<HTMLInputElement[]>([])
let renameTrigger: HTMLElement | null = null

async function startRename(project: Project) {
  if (saving.value) return
  renameTrigger = document.querySelector<HTMLElement>(`[data-test="project-row"][data-project-id="${project.id}"] [data-test="project-actions"]`)
  editing.value = project.id
  name.value = project.name
  error.value = ''
  notice.value = ''
  await nextTick()
  input.value[0]?.focus()
  input.value[0]?.select()
}

async function cancelRename() {
  if (saving.value) return
  editing.value = null
  error.value = ''
  await nextTick()
  if (renameTrigger?.isConnected) renameTrigger.focus()
  else searchInput.value?.focus()
}

async function saveRename() {
  if (saving.value || editing.value === null) return
  const trimmed = name.value.trim()
  if (!trimmed) {
    error.value = 'O nome não pode ficar vazio.'
    return
  }
  if (trimmed.length > 100) {
    error.value = 'Use até 100 caracteres no nome.'
    return
  }
  saving.value = true
  error.value = ''
  try {
    await projects.rename(editing.value, trimmed)
    notice.value = 'Nome do projeto atualizado.'
    saving.value = false
    await cancelRename()
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    saving.value = false
  }
}

async function retry() {
  if (retrying.value) return
  retrying.value = true
  try { await projects.load() }
  catch { /* The shared store displays the load error. */ }
  finally { retrying.value = false }
}
</script>

<template>
  <OrgPage title="Projetos">
    <template #actions>
      <RouterLink to="/projects/new" class="org-button org-primary">Novo projeto</RouterLink>
    </template>

    <p v-if="notice" role="status" class="mb-4 text-sm text-primary">{{ notice }}</p>
    <p v-if="projects.loadError" role="alert" class="org-error mb-4">
      Não foi possível carregar os projetos. {{ projects.loadError }}
      <button type="button" data-test="retry-projects" class="org-button ml-2" :disabled="retrying" @click="retry">{{ retrying ? 'Carregando…' : 'Tentar novamente' }}</button>
    </p>
    <div v-if="!projects.loaded && !projects.regular.length" class="org-skeleton" role="status">
      <span class="sr-only">Carregando projetos…</span><span /><span /><span />
    </div>
    <div v-else-if="projects.loaded && !projects.regular.length && !projects.loadError" class="org-empty">
      <strong>Nenhum projeto cadastrado</strong>
      Adicione uma pasta em Novo projeto para começar.
    </div>
    <template v-if="projects.regular.length">
      <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
        <label class="org-field min-w-0 grow sm:max-w-sm">
          <span class="sr-only">Buscar projetos por nome ou caminho</span>
          <input ref="searchInput" v-model="query" data-test="project-search" type="search" placeholder="Buscar por nome ou caminho" autocomplete="off" />
        </label>
        <p class="org-muted m-0">{{ projects.regular.length }} {{ projects.regular.length === 1 ? 'projeto cadastrado' : 'projetos cadastrados' }}</p>
      </div>
      <p v-if="!visibleProjects.length" role="status" class="org-empty">Nenhum projeto encontrado. Tente outro nome ou caminho.</p>
      <div v-else class="overflow-x-auto">
        <div role="table" aria-label="Projetos cadastrados" class="min-w-[760px]">
          <div role="row" :class="[ROW, 'h-7 border-b border-line-strong font-mono text-[0.65625rem] font-semibold tracking-[0.08em] text-fg-subtle uppercase']">
            <span aria-hidden="true" />
            <span role="columnheader">Projeto</span>
            <span role="columnheader">Branch</span>
            <span role="columnheader">Conversas</span>
            <span role="columnheader">Alterações</span>
            <span role="columnheader" class="text-right">Atividade</span>
            <span role="columnheader" class="sr-only">Ações</span>
          </div>
          <div v-for="group in groups" :key="group.key" role="rowgroup" data-test="project-group" :data-group="group.key" class="mt-2.5 first:mt-1">
            <div role="row"><div role="cell"><GroupHeader :title="group.title" :count="group.projects.length" /></div></div>
            <div v-for="project in group.projects" :key="project.id" role="row" data-test="project-row" :data-project-id="project.id" :class="[ROW, 'min-h-11 border-b border-line py-1 text-[0.8125rem] text-fg-muted hover:bg-panel']">
              <span aria-hidden="true" class="size-2 shrink-0 rounded-sm" :style="{ backgroundColor: project.color }" />
              <div role="cell" class="min-w-0">
                <div class="flex min-w-0 items-baseline gap-2.5">
                  <RouterLink :to="{ name: 'project', params: { id: project.id } }" class="truncate text-[0.90625rem] font-semibold text-fg no-underline hover:underline focus-visible:outline-2 focus-visible:outline-primary">{{ project.name }}</RouterLink>
                  <span data-test="project-path" :title="project.path" class="truncate font-mono text-[0.71875rem] text-fg-subtle">{{ shortPath(project.path) }}</span>
                </div>
                <p v-if="!project.available" class="m-0 text-xs text-secondary-soft">Pasta indisponível</p>
                <form v-if="editing === project.id" class="my-2 flex flex-wrap items-end gap-2" :aria-label="`Renomear ${project.name}`" @submit.prevent="saveRename" @keydown.esc.prevent="cancelRename">
                  <label class="org-field grow" :for="`project-name-${project.id}`">Nome do projeto
                    <input :id="`project-name-${project.id}`" ref="input" v-model="name" type="text" maxlength="100" autocomplete="off" :disabled="saving" :aria-invalid="error ? true : undefined" :aria-describedby="error ? 'project-rename-error' : undefined" />
                  </label>
                  <button type="submit" class="org-button org-primary" :disabled="saving">{{ saving ? 'Salvando…' : 'Salvar' }}</button>
                  <button type="button" class="org-button" :disabled="saving" @click="cancelRename">Cancelar</button>
                  <p v-if="error" id="project-rename-error" role="alert" class="org-error w-full">{{ error }}</p>
                </form>
              </div>
              <span role="cell" data-test="project-branch" class="truncate font-mono text-[0.71875rem]">{{ branchOf(project) }}</span>
              <span role="cell" data-test="project-conversations" class="flex min-w-0 items-center gap-1.5">
                <template v-if="activityOf(project).running">
                  <DisplayStateIcon display="running" />
                  <span class="truncate"><span class="text-primary-soft">{{ activityOf(project).running }} em execução</span>{{ activityOf(project).open ? ` · ${openText(activityOf(project).open)}` : '' }}</span>
                </template>
                <span v-else-if="activityOf(project).open" class="truncate">{{ openText(activityOf(project).open) }}</span>
                <span v-else-if="activityOf(project).latest" class="truncate text-fg-subtle">nenhuma aberta</span>
              </span>
              <span role="cell" data-test="project-changes" class="font-mono text-[0.71875rem] tabular-nums" :class="staleOf(project) !== null && hasRepos(project) ? 'text-secondary-soft' : 'text-fg-muted'">{{ changesText(project) }}</span>
              <span role="cell" data-test="project-activity" class="text-right font-mono text-[0.71875rem] whitespace-nowrap text-fg-subtle tabular-nums">{{ activityText(activityOf(project).latest, now) }}</span>
              <span role="cell"><MoreMenu data-test="project-actions" :label="`Ações de ${project.name}`" :items="actionItems" :disabled="saving || editing === project.id" @select="onAction(project, $event)" /></span>
            </div>
          </div>
        </div>
      </div>
    </template>
  </OrgPage>
</template>
