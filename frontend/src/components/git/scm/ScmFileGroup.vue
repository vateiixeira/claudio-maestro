<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import FileDiffView from '../../details/FileDiffView.vue'
import ScmFileRow from './ScmFileRow.vue'
import IconChevron from '../../icons/IconChevron.vue'
import type { ChangedFile, ChangesGroup, RepoDetails, RepoFile } from '../../../types/api'

const props = defineProps<{
  projectId: number
  repo: RepoDetails
  /** `staged`, `changes`, `conflict` or `ready` (merge). */
  group: string
  title: string
  files: RepoFile[]
  revision: number
  readOnly: boolean
  disabled: boolean
  /** Names of the two branches in the conflict markers of the diff. */
  conflictLabels?: { ours: string; theirs: string } | null
}>()
const emit = defineEmits<{
  stage: [paths: string[]]; unstage: [paths: string[]]; discard: [files: RepoFile[]]; editor: [file: RepoFile]
}>()

const open = ref(true)
const expanded = ref<Record<string, boolean>>({})
const keyOf = (f: RepoFile) => `${f.status}:${f.path}`
watch(() => props.files, (files) => {
  const present = new Set(files.map(keyOf))
  for (const key of Object.keys(expanded.value)) if (!present.has(key)) delete expanded.value[key]
})

const diffGroup = computed<ChangesGroup>(() => ({
  path: props.repo.path, rel_path: props.repo.rel_path, branch: props.repo.branch,
  detached: props.repo.detached, head: props.repo.head, files: [],
}))
const changedFile = (f: RepoFile): ChangedFile => ({
  path: `${props.repo.path}/${f.path}`, rel_path: f.path, added: f.added, removed: f.removed, uncommitted: true,
})
const paths = computed(() => [...new Set(props.files.map((f) => f.path))])
const iconButton = 'flex size-[22px] items-center justify-center rounded text-fg-muted hover:bg-card hover:text-fg disabled:opacity-50'
</script>

<template>
  <div data-test="scm-group" :data-group="group" class="flex flex-col">
    <div class="group flex h-6 items-center gap-1.5 rounded pr-1 hover:bg-elevated focus-within:bg-elevated">
      <button type="button" :aria-expanded="open" class="flex min-w-0 grow items-center gap-1.5 pl-1 text-left text-[0.8125rem] font-medium text-fg-muted" @click="open = !open">
        <IconChevron :open="open" :size="12" class="text-fg-subtle" />
        <span data-test="scm-group-title"><slot name="title">{{ title }}</slot></span>
      </button>
      <span v-if="!readOnly" class="flex shrink-0 items-center w-0 overflow-hidden opacity-0 group-hover:w-auto group-hover:opacity-100 group-focus-within:w-auto group-focus-within:opacity-100">
        <!-- A provided slot may render nothing (no actions at all); only an absent one gets the defaults. -->
        <slot v-if="$slots['group-actions']" name="group-actions" />
        <template v-else>
          <button v-if="group !== 'staged'" type="button" data-test="group-discard-all" :class="iconButton" :disabled="disabled" aria-label="Descartar todas" title="Descartar todas" @click="emit('discard', files)">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5" /></svg>
          </button>
          <button v-if="group === 'staged'" type="button" data-test="group-unstage-all" :class="iconButton" :disabled="disabled" aria-label="Tirar todas da preparação" title="Tirar todas da preparação" @click="emit('unstage', paths)">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><line x1="5" y1="12" x2="19" y2="12" /></svg>
          </button>
          <button v-else type="button" data-test="group-stage-all" :class="iconButton" :disabled="disabled" aria-label="Preparar todas" title="Preparar todas" @click="emit('stage', paths)">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
          </button>
        </template>
      </span>
      <span data-test="scm-group-count" class="min-w-[18px] rounded-full bg-card px-1.5 text-center font-mono text-[0.6875rem] text-fg-muted">{{ paths.length }}</span>
    </div>
    <slot v-if="open" name="note" />
    <ul v-if="open" class="m-0 flex list-none flex-col p-0 pl-4">
      <li v-for="f in files" :key="keyOf(f)" class="flex flex-col">
        <ScmFileRow
          :file="f"
          :open="!!expanded[keyOf(f)]"
          :read-only="readOnly"
          :disabled="disabled"
          @toggle="expanded[keyOf(f)] = !expanded[keyOf(f)]"
          @editor="emit('editor', f)"
          @discard="emit('discard', [f])"
          @stage="emit('stage', [f.path])"
          @unstage="emit('unstage', [f.path])"
        >
          <template v-if="$slots['file-actions']" #actions><slot name="file-actions" :file="f" /></template>
        </ScmFileRow>
        <div v-if="expanded[keyOf(f)]" class="my-0.5 rounded-md border border-line bg-bg px-2 py-1">
          <FileDiffView :project-id="projectId" :group="diffGroup" :file="changedFile(f)" :revision="revision" :conflict-labels="conflictLabels" />
        </div>
      </li>
    </ul>
  </div>
</template>
