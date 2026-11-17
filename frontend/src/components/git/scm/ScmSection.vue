<script lang="ts">
/** From this many repositories on, the list splits into "with pending" and "clear", under a columns row. */
export const GROUPED_FROM = 3
</script>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import ScmRepo from './ScmRepo.vue'
import GroupHeader from '../../ui/GroupHeader.vue'
import { syncCounts } from '../../../git/repoLabel'
import { isPending } from '../../../git/pending'
import { REPO_ROW_GRID } from '../../../git/repoRowGrid'
import { gitTotals, summaryParts } from '../../../git/summary'
import { useGitOpsStore } from '../../../stores/gitOps'
import { useGitDetailsStore } from '../../../stores/gitDetails'
import type { RepoDetails } from '../../../types/api'

const props = defineProps<{ projectId: number; repoPaths?: string[]; openAll?: boolean }>()
const emit = defineEmits<{ history: [path: string] }>()
const details = useGitDetailsStore()
const ops = useGitOpsStore()
const repos = computed(() => details.reposFor(props.projectId))
const visibleRepos = computed(() => props.repoPaths ? repos.value.filter((repo) => props.repoPaths!.includes(repo.path)) : repos.value)
const loaded = computed(() => details.isLoaded(props.projectId))
const error = computed(() => details.errorFor(props.projectId))
const refreshing = computed(() => details.isLoading(props.projectId))
const collapseAll = ref(0)
const parts = computed(() => summaryParts(gitTotals(visibleRepos.value)))
const partClass: Record<string, string> = {
  ahead: 'font-semibold text-secondary-soft',
  behind: 'text-info-soft',
  errors: 'text-diff-del-fg',
}
const grouped = computed(() => visibleRepos.value.length >= GROUPED_FROM)
// The order inside each group is the backend's; a repository changes group without losing its state, which lives by path.
const groups = computed(() => {
  const pending = visibleRepos.value.filter(isPending)
  const clear = visibleRepos.value.filter((repo) => !isPending(repo))
  return [
    { key: 'pending', title: 'Com pendências', repos: pending },
    { key: 'clear', title: 'Sem pendências', repos: clear },
  ].filter((group) => group.repos.length > 0)
})

const textButton = 'h-7 rounded-md border border-line-strong px-2.5 text-xs font-medium text-fg hover:bg-card focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:opacity-60'

const fetchingAll = ref(false)
/** Fetches the repositories that have an upstream; a failure shows on the repository's own row. */
async function fetchAll(): Promise<void> {
  fetchingAll.value = true
  try {
    const targets = repos.value.filter((r) => !r.error && r.upstream != null && !ops.busyFor(r.path))
    await Promise.all(targets.map((r) => ops.run(props.projectId, r.path, 'fetch-repo')))
  } finally {
    fetchingAll.value = false
  }
}

watch(
  () => props.projectId,
  (id, _old, onCleanup) => {
    details.open(id)
    onCleanup(() => details.close(id))
  },
  { immediate: true },
)

// With several repositories, only what needs a decision starts open: errors, changes, a merge, or
// commits both to send and to pull. Just one of the two is a row's worth, shown in its summary.
function opensByDefault(repo: RepoDetails): boolean {
  if (props.openAll || repos.value.length === 1 || repo.error) return true
  const sync = syncCounts(repo)
  return repo.files.length > 0 || repo.state?.merging === true || (sync.ahead > 0 && sync.behind > 0)
}
// A repository that changes group is mounted again in the other list: one that was open by default
// stays so (becoming clean must not collapse a reader), as the row does when it stays in place.
const wasOpen = new Set<string>()
const memoryKey = (path: string) => `${props.projectId}:${path}`
watch(
  () => repos.value.filter(opensByDefault).map((repo) => repo.path),
  (paths) => { for (const path of paths) wasOpen.add(memoryKey(path)) },
  { immediate: true, flush: 'sync' },
)
function startOpen(repo: RepoDetails): boolean {
  return opensByDefault(repo) || wasOpen.has(memoryKey(repo.path))
}
</script>

<template>
  <section data-test="scm-section" aria-labelledby="scm-title" class="flex min-w-0 flex-col gap-2">
    <header class="flex min-h-10 flex-wrap items-center gap-x-3.5 gap-y-1 px-1">
      <h2 id="scm-title" class="sr-only">Alterações</h2>
      <p v-if="loaded" data-test="scm-summary" class="m-0 flex min-w-0 flex-wrap items-center gap-x-3.5 gap-y-0.5 text-[0.8125rem] text-fg-muted">
        <span v-for="part in parts" :key="part.part" data-test="scm-summary-part" :data-part="part.part" :class="partClass[part.part]">{{ part.text }}</span>
      </p>
      <span class="grow" />
      <slot name="header-actions" />
      <button type="button" data-test="scm-fetch-all" title="Buscar em todos" :aria-busy="fetchingAll" :disabled="fetchingAll || !loaded" :class="textButton" @click="fetchAll">Buscar em todos</button>
      <button type="button" data-test="scm-refresh" title="Reler o estado git" :aria-busy="refreshing" :disabled="refreshing" :class="textButton" @click="details.load(projectId)">Atualizar</button>
      <button type="button" data-test="scm-collapse-all" aria-label="Recolher todos" title="Recolher todos" class="flex size-7 items-center justify-center rounded text-fg-muted hover:bg-elevated hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary" @click="collapseAll++">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m7 20 5-5 5 5" /><path d="m7 4 5 5 5-5" /></svg>
      </button>
    </header>
    <p v-if="!loaded && !error" data-test="git-loading" class="m-0 px-1 text-sm text-fg-muted">Carregando…</p>
    <div v-else-if="!loaded" data-test="git-error" class="flex flex-col items-start gap-2 px-1">
      <p role="alert" class="m-0 text-sm text-diff-del-fg">{{ error }}</p>
      <button type="button" data-test="git-retry" class="h-7 rounded-md border border-line-strong px-2.5 text-xs font-medium text-fg hover:bg-card" @click="details.load(projectId)">Tentar de novo</button>
    </div>
    <template v-else>
      <p v-if="error" role="alert" class="m-0 px-1 text-xs text-diff-del-fg">Não foi possível atualizar: {{ error }}</p>
      <ul v-if="!grouped" class="m-0 flex list-none flex-col p-0">
        <ScmRepo v-for="repo in visibleRepos" :key="`${projectId}:${repo.path}`" :project-id="projectId" :repo="repo" :collapse-all="collapseAll" :start-open="startOpen(repo)" @history="emit('history', repo.path)" />
      </ul>
      <template v-else>
        <div class="@container" aria-hidden="true" data-test="scm-columns">
          <div class="hidden h-7 items-center border-b border-line-strong px-2 font-mono text-[0.65625rem] font-semibold tracking-[0.08em] text-fg-subtle uppercase" :class="REPO_ROW_GRID">
            <span class="@3xl:col-start-2">Repositório</span>
            <span class="@3xl:col-start-3">Branch</span>
            <span class="@3xl:col-start-4">Situação</span>
          </div>
        </div>
        <div v-for="group in groups" :key="group.key" data-test="scm-repo-group" :data-group="group.key" role="group" :aria-label="group.title" class="mt-2">
          <GroupHeader :title="group.title" :count="group.repos.length" />
          <ul class="m-0 flex list-none flex-col p-0">
            <ScmRepo v-for="repo in group.repos" :key="`${projectId}:${repo.path}`" :project-id="projectId" :repo="repo" :collapse-all="collapseAll" :start-open="startOpen(repo)" :quiet="group.key === 'clear'" @history="emit('history', repo.path)" />
          </ul>
        </div>
      </template>
    </template>
  </section>
</template>
