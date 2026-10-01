<script setup lang="ts">
import BranchLabel from '../git/BranchLabel.vue'
import WorktreeLabel from '../git/WorktreeLabel.vue'
import { branchText } from '../../stores/git'
import type { ChangedFile, ChangesGroup } from '../../types/api'

defineProps<{
  groups: ChangesGroup[]
  loading: boolean
  error: string | null
  selected: { group: string | null; file: string } | null
}>()
const emit = defineEmits<{ select: [group: ChangesGroup, file: ChangedFile]; retry: [] }>()
</script>

<template>
  <div class="flex flex-col gap-2">
    <div v-if="error" class="flex flex-col items-start gap-2">
      <p data-test="changes-error" role="alert" class="m-0 text-sm text-diff-del-fg">{{ error }}</p>
      <button
        type="button"
        data-test="changes-retry"
        class="h-8 rounded-md border border-line-strong px-2.5 text-xs font-medium text-fg hover:bg-card"
        @click="emit('retry')"
      >Tentar de novo</button>
    </div>
    <p v-else-if="!loading && groups.length === 0" class="m-0 text-sm text-fg-muted">Sem alterações</p>
    <div v-for="group in groups" :key="group.path ?? '-'" class="flex flex-col rounded-lg border border-line">
      <div
        data-test="group-header"
        class="flex items-center gap-2 border-b border-line px-3 py-2"
        :title="group.worktree ? (group.path ?? undefined) : undefined"
      >
        <span v-if="group.worktree" data-test="group-worktree" class="flex min-w-0 font-semibold"><WorktreeLabel :text="group.worktree" /></span>
        <span v-else class="min-w-0 truncate font-mono text-xs font-semibold">{{ group.rel_path ?? 'Fora de repositório' }}</span>
        <BranchLabel v-if="group.rel_path != null" :text="branchText({ ...group, error: null })" muted />
      </div>
      <button
        v-for="file in group.files"
        :key="file.path"
        type="button"
        data-test="changed-file"
        class="flex min-h-9 items-center gap-2 border-b border-line px-3 text-left last:border-b-0 hover:bg-card"
        :aria-pressed="selected?.group === group.path && selected?.file === file.path"
        @click="emit('select', group, file)"
      >
        <span class="min-w-0 grow truncate font-mono text-xs text-fg">{{ file.rel_path }}</span>
        <span v-if="file.uncommitted" class="shrink-0 text-xs text-fg-muted">sem commit</span>
        <span v-if="file.added != null" class="font-mono text-xs text-diff-add-fg">+{{ file.added }}</span>
        <span v-if="file.removed != null" class="font-mono text-xs text-diff-del-fg">−{{ file.removed }}</span>
      </button>
    </div>
  </div>
</template>
