<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import FileDiffView from '../details/FileDiffView.vue'
import { useGitDetailsStore } from '../../stores/gitDetails'
import type { ChangedFile, ChangesGroup, RepoDetails, RepoFile, RepoFileStatus } from '../../types/api'

const props = defineProps<{ projectId: number; repo: RepoDetails }>()

const details = useGitDetailsStore()
// A new revision means the files may have changed on disk: open diffs are reread.
const revision = computed(() => details.revisionFor(props.projectId))

const GROUPS: { status: RepoFileStatus; label: string }[] = [
  { status: 'staged', label: 'Preparados' },
  { status: 'unstaged', label: 'Não preparados' },
  { status: 'untracked', label: 'Novos' },
]

const groups = computed(() =>
  GROUPS
    .map((g) => ({ ...g, files: props.repo.files.filter((f) => f.status === g.status) }))
    .filter((g) => g.files.length > 0),
)

// The diff route takes the repository relative to the project and the file relative to the repository.
const diffGroup = computed<ChangesGroup>(() => ({
  path: props.repo.path,
  rel_path: props.repo.rel_path,
  branch: props.repo.branch,
  detached: props.repo.detached,
  head: props.repo.head,
  files: [],
}))

function changedFile(file: RepoFile): ChangedFile {
  return {
    path: `${props.repo.path}/${file.path}`,
    rel_path: file.path,
    added: file.added,
    removed: file.removed,
    uncommitted: true,
  }
}

const expanded = ref<Record<string, boolean>>({})
const keyOf = (file: RepoFile) => `${file.status}:${file.path}`
// Files that left the list must not come back already expanded.
watch(() => props.repo.files, (files) => {
  const present = new Set(files.map(keyOf))
  for (const key of Object.keys(expanded.value)) {
    if (!present.has(key)) delete expanded.value[key]
  }
})
function toggle(file: RepoFile): void {
  expanded.value[keyOf(file)] = !expanded.value[keyOf(file)]
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <section
      v-for="group in groups"
      :key="group.status"
      data-test="file-group"
      class="flex flex-col gap-1"
    >
      <h4 data-test="file-group-title" class="m-0 font-mono text-[11px] tracking-[0.08em] text-fg-muted uppercase">{{ group.label }}</h4>
      <ul class="m-0 flex list-none flex-col p-0">
        <li v-for="file in group.files" :key="keyOf(file)" data-test="file-row" class="flex flex-col">
          <button
            type="button"
            :title="file.path"
            :aria-expanded="!!expanded[keyOf(file)]"
            class="flex min-h-8 w-full items-center gap-2 rounded-md px-2 text-left hover:bg-card"
            @click="toggle(file)"
          >
            <span class="shrink-0 text-fg-muted" aria-hidden="true">{{ expanded[keyOf(file)] ? '▾' : '▸' }}</span>
            <span class="min-w-0 grow truncate font-mono text-xs">{{ file.path }}</span>
            <span v-if="file.added != null" class="shrink-0 font-mono text-xs text-diff-add-fg">+{{ file.added }}</span>
            <span v-if="file.removed != null" class="shrink-0 font-mono text-xs text-diff-del-fg">−{{ file.removed }}</span>
          </button>
          <div v-if="expanded[keyOf(file)]" class="px-2 pt-1 pb-2">
            <FileDiffView :project-id="projectId" :group="diffGroup" :file="changedFile(file)" :revision="revision" />
          </div>
        </li>
      </ul>
    </section>
    <p v-if="repo.files_truncated" data-test="files-truncated" class="m-0 text-xs text-secondary-soft">
      Há mais arquivos alterados do que a lista mostra.
    </p>
  </div>
</template>
