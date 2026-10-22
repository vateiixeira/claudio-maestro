<script setup lang="ts">
import { computed, ref, useId } from 'vue'
import BranchLabel from '../git/BranchLabel.vue'
import IconChevron from '../icons/IconChevron.vue'
import BranchSync from './BranchSync.vue'
import { syncState } from '../../gitSync'
import { repoLabel } from '../../stores/git'
import type { GitRepo } from '../../types/api'

// The branch of each repository of a project in Detalhes. With several repositories only the first
// one shows at first; the rest sit behind a toggle so the property does not take over the panel.
const props = defineProps<{ projectId: number; repos: GitRepo[] }>()

const open = ref(false)
const moreId = useId()

const first = computed(() => props.repos[0])
const rest = computed(() => props.repos.slice(1))
const toggleText = computed(() => (open.value ? 'menos' : `+ ${rest.value.length} ${rest.value.length === 1 ? 'repositório' : 'repositórios'}`))
// Something in a hidden repository that the user would want to notice: commits to pull or a failure.
const hiddenNeedsAttention = computed(() => !open.value && rest.value.some((repo) => {
  if (repo.error || repo.fetch_error) return true
  const kind = syncState(repo).kind
  return kind === 'behind' || kind === 'diverged'
}))
</script>

<template>
  <div class="flex min-w-0 flex-col gap-1">
    <div v-if="first" class="flex min-w-0 flex-col gap-0.5">
      <BranchLabel :text="repoLabel(first)" :muted="!!first.error" />
      <BranchSync v-if="!first.error" :project-id="projectId" :repo="first" />
    </div>
    <div v-if="open" :id="moreId" data-test="prop-branch-more" class="flex min-w-0 flex-col gap-1">
      <div v-for="repo in rest" :key="repo.path" class="flex min-w-0 flex-col gap-0.5">
        <BranchLabel :text="repoLabel(repo)" :muted="!!repo.error" />
        <BranchSync v-if="!repo.error" :project-id="projectId" :repo="repo" />
      </div>
    </div>
    <button
      v-if="rest.length > 0"
      type="button"
      data-test="prop-branch-toggle"
      class="flex w-fit cursor-pointer items-center gap-1 rounded-sm text-xs text-fg-subtle hover:text-fg focus-visible:outline-2 focus-visible:outline-primary"
      :aria-expanded="open"
      :aria-controls="open ? moreId : undefined"
      @click="open = !open"
    >
      <IconChevron :size="10" :open="false" :class="open ? '-rotate-90' : 'rotate-90'" />{{ toggleText }}<span
        v-if="hiddenNeedsAttention"
        data-test="prop-branch-attention"
        class="size-1.5 shrink-0 rounded-full bg-secondary-soft"
        title="Há algo para ver nos repositórios escondidos"
      /><span v-if="hiddenNeedsAttention" class="sr-only">, um repositório escondido pede atenção</span>
    </button>
  </div>
</template>
