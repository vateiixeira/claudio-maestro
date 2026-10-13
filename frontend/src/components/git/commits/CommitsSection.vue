<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import CommitsRepo from './CommitsRepo.vue'
import { useGitDetailsStore } from '../../../stores/gitDetails'

const props = defineProps<{ projectId: number }>()
const details = useGitDetailsStore()
const repos = computed(() => details.reposFor(props.projectId).filter((r) => !r.error))
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
</script>

<template>
  <section v-if="repos.length > 0" data-test="commits-section" aria-labelledby="commits-title" class="flex flex-col">
    <header class="flex h-7 items-center gap-2 px-1">
      <h2 id="commits-title" data-test="commits-title" class="m-0 font-mono text-[0.65625rem] font-semibold tracking-[0.08em] text-fg-subtle uppercase">Commits</h2>
      <span data-test="commits-count" class="text-xs text-fg-subtle">{{ countText }}</span>
      <span class="grow" />
      <button type="button" data-test="commits-refresh" aria-label="Atualizar" title="Reler o estado git" class="flex size-6 items-center justify-center rounded text-fg-muted hover:bg-elevated hover:text-fg" @click="details.load(projectId)">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a9 9 0 1 1-2.64-6.36" /><path d="M21 3v6h-6" /></svg>
      </button>
      <button type="button" data-test="commits-collapse-all" aria-label="Recolher todos" title="Recolher todos" class="flex size-6 items-center justify-center rounded text-fg-muted hover:bg-elevated hover:text-fg" @click="collapseAll++">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m7 20 5-5 5 5" /><path d="m7 4 5 5 5-5" /></svg>
      </button>
    </header>
    <ul class="m-0 flex list-none flex-col p-0">
      <CommitsRepo v-for="repo in repos" :key="repo.path" :project-id="projectId" :repo="repo" :collapse-all="collapseAll" />
    </ul>
  </section>
</template>
