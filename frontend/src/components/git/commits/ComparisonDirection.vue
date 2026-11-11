<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { errorMessage, getComparisonCommits, getComparisonDiff, getComparisonFiles } from '../../../api/http'
import type { BranchComparison, ComparisonDirection, ComparisonFiles, FileDiff, LogCommit } from '../../../types/api'
import { diffFromUnified } from '../../../conversation/diff'
import DiffLines from '../../conversation/DiffLines.vue'
import IconChevron from '../../icons/IconChevron.vue'
import CommitRow from './CommitRow.vue'

const props = defineProps<{ projectId: number; repoPath: string; comparison: BranchComparison; direction: ComparisonDirection; userEmail: string | null }>()
const commits = ref<LogCommit[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const nextSkip = ref<number | null>(null)
const filesOpen = ref(false)
const files = ref<ComparisonFiles | null>(null)
const filesError = ref<string | null>(null)
const filesLoading = ref(false)
const selectedFile = ref<string | null>(null)
const diff = ref<FileDiff | null>(null)
const diffError = ref<string | null>(null)
const controller = new AbortController()
let alive = true
let diffGeneration = 0
let diffController: AbortController | undefined
onBeforeUnmount(() => { alive = false; controller.abort(); diffGeneration++; diffController?.abort() })
const args = () => [props.projectId, props.repoPath, props.comparison.head_sha, props.comparison.base_sha, props.direction] as const

async function loadMore(): Promise<void> {
  if (loading.value) return
  loading.value = true
  error.value = null
  try {
    const result = await getComparisonCommits(...args(), nextSkip.value ?? 0, controller.signal)
    if (!alive) return
    commits.value = [...new Map([...commits.value, ...result.commits].map(c => [c.full_hash, c])).values()]
    nextSkip.value = result.has_more ? result.next_skip : null
  } catch (e) { if (alive) error.value = errorMessage(e) }
  finally { if (alive) loading.value = false }
}
onMounted(loadMore)

async function loadFiles(): Promise<void> {
  if (filesLoading.value) return
  filesError.value = null
  filesLoading.value = true
  try {
    const result = await getComparisonFiles(...args(), controller.signal)
    if (alive) files.value = result
  } catch (e) { if (alive) filesError.value = errorMessage(e) }
  finally { if (alive) filesLoading.value = false }
}
function toggleFiles(): void {
  filesOpen.value = !filesOpen.value
  if (filesOpen.value && !files.value) void loadFiles()
}
async function selectFile(file: string): Promise<void> {
  const mine = ++diffGeneration
  diffController?.abort()
  diffController = new AbortController()
  selectedFile.value = selectedFile.value === file ? null : file
  diff.value = null
  diffError.value = null
  if (!selectedFile.value) return
  try {
    const result = await getComparisonDiff(...args(), file, diffController.signal)
    if (alive && mine === diffGeneration) diff.value = result
  } catch (e) { if (alive && mine === diffGeneration) diffError.value = errorMessage(e) }
}
</script>

<template>
  <div class="min-w-0 pl-4" data-test="comparison-direction">
    <p v-if="error" role="alert" class="m-0 py-1 text-xs text-diff-del-fg">{{ error }} <button type="button" class="underline" @click="loadMore">Tentar novamente</button></p>
    <p v-if="loading && !commits.length" class="m-0 py-1 text-xs text-fg-muted">Carregando commits…</p>
    <ul class="m-0 list-none p-0">
      <CommitRow v-for="commit in commits" :key="commit.full_hash" :project-id="projectId" :repo-path="repoPath" :commit="commit" :upstream-label="null" :user-email="userEmail" />
    </ul>
    <p v-if="!loading && !error && !commits.length" class="m-0 py-1 text-xs text-fg-muted">Nenhum commit neste sentido.</p>
    <button v-if="nextSkip !== null" type="button" data-test="comparison-load-more" :disabled="loading" class="min-h-6 rounded px-1.5 text-xs text-fg-muted hover:bg-elevated" @click="loadMore">{{ loading ? 'Carregando…' : 'Carregar mais commits' }}</button>
    <template v-if="!comparison.unrelated">
      <button type="button" data-test="comparison-files-toggle" :aria-expanded="filesOpen" class="flex min-h-6 items-center gap-1.5 text-xs text-fg-muted hover:text-fg" @click="toggleFiles">
        <IconChevron :open="filesOpen" :size="12" />Arquivos desde o ancestral comum
      </button>
      <div v-if="filesOpen" class="min-w-0 pl-4">
        <p v-if="filesError" role="alert" class="m-0 py-1 text-xs text-diff-del-fg">{{ filesError }} <button type="button" class="underline" @click="loadFiles">Tentar novamente</button></p>
        <p v-if="filesLoading" class="m-0 py-1 text-xs text-fg-muted">Carregando arquivos…</p>
        <ul v-if="files" class="m-0 list-none p-0">
          <li v-for="file in files.files" :key="file.path">
            <button type="button" data-test="comparison-file" :aria-expanded="selectedFile === file.path" :title="file.old_path ? `${file.old_path} → ${file.path}` : file.path" class="flex min-h-6 w-full min-w-0 items-center gap-2 rounded px-1 text-left text-xs hover:bg-elevated" @click="selectFile(file.path)">
              <span class="grow truncate text-fg">{{ file.path }}</span><span class="shrink-0 font-mono text-fg-subtle">{{ file.status }}</span>
            </button>
            <div v-if="selectedFile === file.path" class="min-w-0 overflow-x-auto py-1">
              <p v-if="diffError" role="alert" class="m-0 text-xs text-diff-del-fg">{{ diffError }}</p>
              <p v-else-if="!diff" class="m-0 text-xs text-fg-muted">Carregando diff…</p>
              <template v-else>
                <p v-if="diff.notice" class="m-0 text-xs text-fg-muted">{{ diff.notice }}</p>
                <DiffLines :lines="diffFromUnified(diff.diff)" />
                <p v-if="diff.truncated" class="m-0 text-xs text-fg-muted">Diff cortado: o arquivo é grande demais.</p>
              </template>
            </div>
          </li>
        </ul>
        <p v-if="files?.files.length === 0" class="m-0 py-1 text-xs text-fg-muted">Nenhum arquivo alterado neste sentido.</p>
        <p v-if="files?.files_truncated" class="m-0 py-1 text-xs text-fg-muted">Há mais arquivos do que esta lista mostra.</p>
      </div>
    </template>
  </div>
</template>
