<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import ScmSection from './scm/ScmSection.vue'
import CommitsSection from './commits/CommitsSection.vue'
import { useGitDetailsStore } from '../../stores/gitDetails'
import { useProjectsStore } from '../../stores/projects'
import FilterChip from '../ui/FilterChip.vue'
import { repoLabel } from '../../git/repoLabel'
import { isPending } from '../../git/pending'

// `focusPath`: a folder (a worktree) whose repositories the panel starts on; "Ver todos" widens it to the project.
const props = defineProps<{ projectId: number; focusPath?: string | null }>()
const details = useGitDetailsStore()
const projects = useProjectsStore()
const query = ref('')
const pendingOnly = ref(false)
const view = ref<'changes' | 'commits'>('changes')
const historyHeading = ref<HTMLElement | null>(null)
const historyVisited = ref(false)
const historyPath = ref<string | null>(null)
const allRepos = computed(() => details.reposFor(props.projectId))
const showAll = ref(false)
const insideFocus = (path: string) => {
  const folder = (props.focusPath ?? '').replace(/\/+$/, '')
  return folder !== '' && (path === folder || path.startsWith(`${folder}/`))
}
// Without any repository under the folder (not listed yet, past the limit) the focus would show nothing: it is ignored.
const focused = computed(() => (!showAll.value && props.focusPath ? allRepos.value.filter((repo) => insideFocus(repo.path)) : []))
const focusing = computed(() => focused.value.length > 0)
const repos = computed(() => (focusing.value ? focused.value : allRepos.value))
const matching = computed(() => {
  const text = query.value.trim().toLocaleLowerCase()
  return repos.value.filter((repo) => {
    return (!pendingOnly.value || isPending(repo)) && (!text || [repoLabel(repo, projects.byId(props.projectId)?.name), repo.path, repo.branch ?? ''].some((value) => value.toLocaleLowerCase().includes(text)))
  })
})
const historyAvailable = computed(() => matching.value.some((repo) => !repo.error))
const paths = computed(() => matching.value.map((repo) => repo.path))
const historyPaths = computed(() => historyPath.value ? paths.value.filter((path) => path === historyPath.value) : paths.value)
const selectedHistory = computed(() => allRepos.value.find((repo) => repo.path === historyPath.value))
function clearFilters() {
  query.value = ''
  pendingOnly.value = false
}
async function showHistory(path: string) {
  historyPath.value = path
  view.value = 'commits'
  await nextTick()
  historyHeading.value?.focus()
}
watch(() => props.focusPath, () => {
  showAll.value = false
  historyPath.value = null
})
watch(allRepos, (value) => { if (historyPath.value && !value.some((repo) => repo.path === historyPath.value)) historyPath.value = null })
watch(view, (value) => {
  if (value === 'commits') historyVisited.value = true
  else historyPath.value = null
})
watch([query, pendingOnly], () => { historyPath.value = null })
watch(() => props.projectId, () => {
  clearFilters()
  historyPath.value = null
  view.value = 'changes'
  historyVisited.value = false
})
</script>

<template>
  <div data-test="git-panel" class="@container flex min-w-0 flex-col gap-3">
    <div class="flex flex-wrap items-center gap-2">
      <div role="group" aria-label="Visualização do Git" class="inline-flex rounded-md border border-line p-0.5">
        <button type="button" data-test="git-view-changes" :aria-pressed="view === 'changes'" class="rounded px-3 py-1.5 text-xs font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary" :class="view === 'changes' ? 'bg-elevated text-fg' : 'text-fg-muted hover:text-fg'" @click="view = 'changes'">Alterações</button>
        <button type="button" data-test="git-view-commits" :aria-pressed="view === 'commits'" class="rounded px-3 py-1.5 text-xs font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary" :class="view === 'commits' ? 'bg-elevated text-fg' : 'text-fg-muted hover:text-fg'" @click="view = 'commits'; historyPath = null">Commits</button>
      </div>
      <span class="flex-1" />
      <span v-if="details.isLoaded(projectId)" data-test="git-match-count" class="font-mono text-xs text-fg-muted tabular-nums" aria-live="polite">{{ matching.length }} de {{ repos.length }}</span>
      <label class="flex h-8 min-w-40 flex-[1_1_12rem] items-center gap-2 rounded-lg border border-line-strong px-2.5 text-fg-muted focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-primary @3xl:w-60 @3xl:flex-none">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
        <input v-model="query" type="search" name="git-repository-search" autocomplete="off" data-test="git-repo-search" aria-label="Buscar repositórios ou branches" placeholder="Buscar repositório ou branch" class="min-w-0 flex-1 border-0 bg-transparent text-[0.8125rem] text-fg outline-none placeholder:text-fg-muted">
      </label>
      <FilterChip data-test="git-pending-filter" label="Só com pendências" :pressed="pendingOnly" @toggle="pendingOnly = !pendingOnly" />
    </div>
    <div v-if="focusing" data-test="git-focus" class="flex flex-wrap items-center gap-2 text-xs">
      <span class="min-w-0 text-fg-muted">Só a worktree da conversa</span>
      <button type="button" data-test="git-focus-all" class="rounded px-2 py-1 text-info-soft hover:bg-elevated focus-visible:outline-2 focus-visible:outline-primary" @click="showAll = true">Ver todos</button>
    </div>
    <div v-if="view === 'commits' && selectedHistory" class="flex flex-wrap items-center gap-2 text-xs">
      <span ref="historyHeading" tabindex="-1" class="min-w-0 truncate text-fg-muted focus-visible:outline-2 focus-visible:outline-primary" :title="selectedHistory.path">Histórico de {{ repoLabel(selectedHistory, projects.byId(projectId)?.name) }}</span>
      <button type="button" data-test="git-all-history" class="rounded px-2 py-1 text-info-soft hover:bg-elevated focus-visible:outline-2 focus-visible:outline-primary" @click="historyPath = null">Ver todos os repositórios</button>
    </div>
    <div v-if="details.isLoaded(projectId) && !matching.length && (query.trim() || pendingOnly)" data-test="git-filter-empty" class="flex flex-wrap items-center gap-2 py-4 text-sm text-fg-muted">
      <span>Nenhum repositório corresponde aos filtros.</span>
      <button type="button" data-test="git-clear-filters" class="rounded px-2 py-1 text-info-soft hover:bg-elevated focus-visible:outline-2 focus-visible:outline-primary" @click="clearFilters">Limpar filtros</button>
    </div>
    <ScmSection v-show="view === 'changes'" :project-id="projectId" :repo-paths="paths" :open-all="focusing" @history="showHistory" />
    <p v-if="view === 'commits' && !details.isLoaded(projectId) && !details.errorFor(projectId)" class="m-0 text-sm text-fg-muted">Carregando…</p>
    <div v-if="view === 'commits' && details.errorFor(projectId)" class="flex items-center gap-2 text-xs text-diff-del-fg">
      <p role="alert">{{ details.errorFor(projectId) }}</p>
      <button type="button" class="underline" @click="details.load(projectId)">Tentar de novo</button>
    </div>
    <p v-if="view === 'commits' && matching.length && !historyAvailable" class="m-0 text-sm text-fg-muted">O histórico está indisponível para os repositórios com erro. Confira o motivo em Alterações.</p>
    <CommitsSection v-if="historyVisited" v-show="view === 'commits'" :project-id="projectId" :repo-paths="historyPaths" :focus-path="historyPath" :active="view === 'commits'" />
  </div>
</template>
