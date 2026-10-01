<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import BranchLabel from './BranchLabel.vue'
import RepoCommitList from './RepoCommitList.vue'
import RepoFileList from './RepoFileList.vue'
import { branchText, changedCount } from '../../stores/git'
import { useGitDetailsStore } from '../../stores/gitDetails'
import { useProjectsStore } from '../../stores/projects'
import type { RepoDetails } from '../../types/api'

const props = defineProps<{ projectId: number }>()

const details = useGitDetailsStore()
const projects = useProjectsStore()
const repos = computed(() => details.reposFor(props.projectId))
const error = computed(() => details.errorFor(props.projectId))
const loaded = computed(() => details.isLoaded(props.projectId))
const refreshing = computed(() => details.isLoading(props.projectId))

// Keeps the details fresh while this screen is on the project.
watch(
  () => props.projectId,
  (id, _old, onCleanup) => {
    details.open(id)
    onCleanup(() => details.close(id))
  },
  { immediate: true },
)

function repoName(repo: RepoDetails): string {
  return repo.rel_path === '.' ? (projects.byId(props.projectId)?.name ?? '.') : repo.rel_path
}

type Sync = { kind: 'none' | 'unavailable' | 'synced' | 'diverged'; ahead: number; behind: number }
function syncOf(repo: RepoDetails): Sync {
  if (repo.upstream == null) return { kind: 'none', ahead: 0, behind: 0 }
  if (repo.ahead == null || repo.behind == null) return { kind: 'unavailable', ahead: 0, behind: 0 }
  const kind = repo.ahead === 0 && repo.behind === 0 ? 'synced' : 'diverged'
  return { kind, ahead: repo.ahead, behind: repo.behind }
}

/** Distinct files not committed: one changed both staged and unstaged counts once. */
function uncommitted(repo: RepoDetails): number {
  const distinct = new Set(repo.files.map((f) => f.path)).size
  return distinct > 0 ? distinct : changedCount(repo)
}

function stateText(repo: RepoDetails): string {
  const n = uncommitted(repo)
  return n === 0 ? 'limpo' : `${n} não commitados`
}

// With several repositories, the clean ones in sync start as just a header.
const revealed = ref<Record<string, boolean>>({})
function collapsible(repo: RepoDetails): boolean {
  return repos.value.length > 1 && !repo.error && uncommitted(repo) === 0 && syncOf(repo).kind === 'synced'
}
function isCollapsed(repo: RepoDetails): boolean {
  return collapsible(repo) && !revealed.value[repo.path]
}
</script>

<template>
  <div v-if="!loaded && !error" data-test="git-loading" class="text-sm text-fg-muted">Carregando…</div>
  <div v-else-if="!loaded" data-test="git-error" class="flex flex-col items-start gap-2">
    <p role="alert" class="m-0 text-sm text-diff-del-fg">{{ error }}</p>
    <button
      type="button"
      data-test="git-retry"
      class="h-8 rounded-md border border-line-strong px-2.5 text-xs font-medium text-fg hover:bg-card"
      @click="details.load(projectId)"
    >Tentar de novo</button>
  </div>
  <div v-else-if="repos.length > 0" class="flex flex-col gap-3">
    <div class="flex items-center gap-3">
      <p v-if="error" role="alert" class="m-0 min-w-0 text-xs text-diff-del-fg">Não foi possível atualizar: {{ error }}</p>
      <!-- Edits made outside the app only show up here or on the periodic check. -->
      <button
        type="button"
        data-test="git-refresh"
        aria-label="Atualizar"
        title="Reler o estado git"
        :aria-busy="refreshing"
        :disabled="refreshing"
        class="ml-auto flex h-8 cursor-pointer items-center gap-1.5 rounded-md border border-line-strong px-2.5 text-xs font-medium text-fg hover:bg-card focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-default disabled:opacity-60"
        @click="details.load(projectId)"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" :class="{ 'motion-safe:animate-spin': refreshing }"><path d="M21 12a9 9 0 1 1-2.64-6.36" /><path d="M21 3v6h-6" /></svg>
        <span aria-hidden="true">Atualizar</span>
      </button>
    </div>
    <article
      v-for="repo in repos"
      :key="repo.path"
      data-test="repo"
      class="flex flex-col gap-3 rounded-lg border border-line bg-panel px-4 py-3"
    >
      <header class="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span data-test="repo-name" class="min-w-0 font-mono text-[13px] font-semibold">{{ repoName(repo) }}</span>
        <BranchLabel :text="branchText(repo)" :muted="!!repo.error" />
        <template v-if="!repo.error">
          <span
            data-test="repo-sync"
            title="“Para baixar” reflete o último fetch; o Vibing não consulta o servidor remoto."
            class="flex items-center gap-2 text-xs"
          >
            <span v-if="syncOf(repo).kind === 'none'" class="text-fg-subtle">sem upstream</span>
            <span v-else-if="syncOf(repo).kind === 'unavailable'" class="text-fg-muted">upstream indisponível</span>
            <span v-else-if="syncOf(repo).kind === 'synced'" class="text-fg-subtle">em dia com {{ repo.upstream }}</span>
            <template v-else>
              <span v-if="syncOf(repo).ahead > 0" class="text-fg-muted"><span aria-hidden="true">↑</span>{{ syncOf(repo).ahead }} para subir</span>
              <span v-if="syncOf(repo).behind > 0" class="text-info"><span aria-hidden="true">↓</span>{{ syncOf(repo).behind }} para baixar</span>
            </template>
          </span>
          <span
            data-test="repo-state"
            class="text-xs"
            :class="uncommitted(repo) > 0 ? 'text-fg-muted' : 'text-fg-subtle'"
          >{{ stateText(repo) }}</span>
        </template>
        <button
          v-if="collapsible(repo)"
          type="button"
          data-test="repo-toggle"
          :aria-expanded="!isCollapsed(repo)"
          class="ml-auto h-8 rounded-md border border-line-strong px-2.5 text-xs font-medium text-fg hover:bg-card"
          @click="revealed[repo.path] = !revealed[repo.path]"
        >{{ isCollapsed(repo) ? 'mostrar commits' : 'ocultar commits' }}</button>
      </header>

      <p v-if="repo.error" data-test="repo-error" role="alert" class="m-0 text-sm text-diff-del-fg">{{ repo.error }}</p>
      <template v-else-if="!isCollapsed(repo)">
        <RepoFileList v-if="repo.files.length > 0" :project-id="projectId" :repo="repo" />
        <RepoCommitList :commits="repo.commits" />
      </template>
    </article>
  </div>
</template>
