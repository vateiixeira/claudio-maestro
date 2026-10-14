<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import ScmRepo from './ScmRepo.vue'
import { syncCounts } from '../../../git/repoLabel'
import { useGitDetailsStore } from '../../../stores/gitDetails'
import type { RepoDetails } from '../../../types/api'

const props = defineProps<{ projectId: number }>()
const details = useGitDetailsStore()
const repos = computed(() => details.reposFor(props.projectId))
const loaded = computed(() => details.isLoaded(props.projectId))
const error = computed(() => details.errorFor(props.projectId))
const refreshing = computed(() => details.isLoading(props.projectId))
const collapseAll = ref(0)
const countText = computed(() => (repos.value.length === 1 ? '1 repositório' : `${repos.value.length} repositórios`))

watch(
  () => props.projectId,
  (id, _old, onCleanup) => {
    details.open(id)
    onCleanup(() => details.close(id))
  },
  { immediate: true },
)

// With several repositories, the clean ones in sync start as just their row.
function startOpen(repo: RepoDetails): boolean {
  if (repos.value.length === 1 || repo.error) return true
  return repo.files.length > 0 || repo.state?.merging === true || syncCounts(repo).kind === 'diverged'
}
</script>

<template>
  <section data-test="scm-section" aria-labelledby="scm-title" class="flex flex-col">
    <header class="flex h-7 items-center gap-2 px-1">
      <h2 id="scm-title" class="m-0 font-mono text-[0.65625rem] font-semibold tracking-[0.08em] text-fg-subtle uppercase">Alterações</h2>
      <span v-if="loaded" data-test="scm-count" class="text-xs text-fg-subtle">{{ countText }}</span>
      <span class="grow" />
      <slot name="header-actions" />
      <button type="button" data-test="scm-refresh" aria-label="Atualizar" title="Reler o estado git" :aria-busy="refreshing" :disabled="refreshing" class="flex size-6 items-center justify-center rounded text-fg-muted hover:bg-elevated hover:text-fg disabled:opacity-60" @click="details.load(projectId)">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" :class="{ 'motion-safe:animate-spin': refreshing }"><path d="M21 12a9 9 0 1 1-2.64-6.36" /><path d="M21 3v6h-6" /></svg>
      </button>
      <button type="button" data-test="scm-collapse-all" aria-label="Recolher todos" title="Recolher todos" class="flex size-6 items-center justify-center rounded text-fg-muted hover:bg-elevated hover:text-fg" @click="collapseAll++">
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
      <ul class="m-0 flex list-none flex-col p-0">
        <ScmRepo v-for="repo in repos" :key="repo.path" :project-id="projectId" :repo="repo" :collapse-all="collapseAll" :start-open="startOpen(repo)" />
      </ul>
    </template>
  </section>
</template>
