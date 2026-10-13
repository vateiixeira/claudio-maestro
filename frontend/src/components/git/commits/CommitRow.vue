<script setup lang="ts">
import { computed, ref } from 'vue'
import DiffLines from '../../conversation/DiffLines.vue'
import IconChevron from '../../icons/IconChevron.vue'
import IconArrowUp from '../../icons/IconArrowUp.vue'
import IconCopy from '../../icons/IconCopy.vue'
import { diffFromUnified } from '../../../conversation/diff'
import { errorMessage } from '../../../api/http'
import { formatActivity } from '../../../format'
import { useGitLogStore } from '../../../stores/gitLog'
import type { CommitDetail, CommitFile, FileDiff, LogCommit } from '../../../types/api'

const props = defineProps<{
  projectId: number
  repoPath: string
  commit: LogCommit
  /** Remote name shown on the commit the upstream points at ("origin"); null elsewhere. */
  upstreamLabel: string | null
  userEmail: string | null
}>()

const log = useGitLogStore()
const open = ref(false)
const detail = ref<CommitDetail | null>(null)
const error = ref<string | null>(null)
const openFile = ref<string | null>(null)
const diff = ref<FileDiff | null>(null)
const diffError = ref<string | null>(null)
const copied = ref<'hash' | 'message' | null>(null)

const who = computed(() => (props.userEmail && props.commit.email === props.userEmail ? 'Você' : props.commit.author))
const when = computed(() => formatActivity(Date.parse(props.commit.date) / 1000))
const message = computed(() => (props.commit.body ? `${props.commit.subject}\n\n${props.commit.body}` : props.commit.subject))

async function toggle(): Promise<void> {
  open.value = !open.value
  if (!open.value || detail.value) return
  error.value = null
  try {
    detail.value = await log.commit(props.projectId, props.repoPath, props.commit.full_hash)
  } catch (e) {
    error.value = errorMessage(e)
  }
}

async function toggleFile(file: CommitFile): Promise<void> {
  if (openFile.value === file.path) { openFile.value = null; return }
  openFile.value = file.path
  diff.value = null
  diffError.value = null
  try {
    diff.value = await log.commitDiff(props.projectId, props.repoPath, props.commit.full_hash, file.path)
  } catch (e) {
    diffError.value = errorMessage(e)
  }
}

async function copy(kind: 'hash' | 'message'): Promise<void> {
  try {
    await navigator.clipboard.writeText(kind === 'hash' ? props.commit.full_hash : message.value)
    copied.value = kind
    setTimeout(() => { if (copied.value === kind) copied.value = null }, 1500)
  } catch {
    copied.value = null
  }
}

const folder = (path: string) => (path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '')
const base = (path: string) => path.slice(path.lastIndexOf('/') + 1)
const LETTER_CLASS: Record<string, string> = { M: 'text-fg-muted', A: 'text-diff-add-fg', C: 'text-diff-add-fg', D: 'text-diff-del-fg', R: 'text-info-soft' }
</script>

<template>
  <li data-test="commit-row" class="flex flex-col">
    <div class="group flex h-6 items-center gap-1.5 rounded px-1 hover:bg-elevated" :class="{ 'bg-card': open }">
      <button
        type="button"
        data-test="commit-toggle"
        :aria-expanded="open"
        :title="commit.full_hash"
        class="flex min-w-0 grow items-center gap-1.5 text-left"
        @click="toggle"
      >
        <IconChevron :open="open" :size="12" class="text-fg-subtle" />
        <span v-if="commit.pushed === false" data-test="commit-unpushed" class="flex shrink-0 text-fg" role="img" aria-label="Ainda não enviado" title="Ainda não enviado"><IconArrowUp :size="12" /></span>
        <span v-else aria-hidden="true" class="mx-[3px] size-1.5 shrink-0 rounded-full bg-fg-subtle" />
        <span v-if="upstreamLabel" data-test="upstream-tag" class="shrink-0 rounded-full border border-info-soft px-1.5 font-mono text-[0.625rem] leading-4 text-info-soft">{{ upstreamLabel }}</span>
        <span class="min-w-0 truncate text-[0.8125rem] text-fg">{{ commit.subject }}</span>
      </button>
      <span class="shrink-0 text-xs text-fg-subtle group-hover:hidden group-focus-within:hidden">{{ who }}, {{ when }}</span>
      <span class="hidden shrink-0 items-center group-hover:flex group-focus-within:flex">
        <button type="button" data-test="copy-hash" class="flex size-6 items-center justify-center rounded text-fg-muted hover:bg-card hover:text-fg" :aria-label="copied === 'hash' ? 'Hash copiado' : 'Copiar hash'" :title="copied === 'hash' ? 'Copiado' : 'Copiar hash'" @click="copy('hash')"><IconCopy :size="14" /></button>
        <button type="button" data-test="copy-message" class="flex h-6 items-center rounded px-1.5 text-xs text-fg-muted hover:bg-card hover:text-fg" @click="copy('message')">{{ copied === 'message' ? 'Copiado' : 'Copiar mensagem' }}</button>
      </span>
    </div>

    <div v-if="open" data-test="commit-detail" class="my-1 ml-5 flex flex-col gap-2 rounded-md border border-line bg-bg px-3 py-2">
      <p v-if="error" role="alert" class="m-0 text-xs text-diff-del-fg">{{ error }}</p>
      <template v-else>
        <p class="m-0 flex flex-wrap gap-x-3 font-mono text-[0.6875rem] text-fg-subtle">
          <span class="select-all">{{ commit.full_hash }}</span>
          <span>{{ commit.author }} &lt;{{ commit.email }}&gt;</span>
          <span>{{ new Date(commit.date).toLocaleString('pt-BR') }}</span>
        </p>
        <p v-if="commit.body" class="m-0 text-[0.8125rem] whitespace-pre-wrap text-fg">{{ commit.body }}</p>
        <p v-if="!detail" class="m-0 text-xs text-fg-muted">Carregando…</p>
        <ul v-else class="m-0 flex list-none flex-col p-0">
          <li v-for="file in detail.files" :key="file.path" data-test="commit-file" class="flex flex-col">
            <button type="button" :aria-expanded="openFile === file.path" class="flex h-6 w-full items-center gap-2 rounded px-1 text-left hover:bg-elevated" :title="file.old_path ? `${file.old_path} → ${file.path}` : file.path" @click="toggleFile(file)">
              <span class="min-w-0 grow truncate"><span class="text-[0.8125rem] text-fg">{{ base(file.path) }}</span><span class="ml-2 font-mono text-[0.6875rem] text-fg-subtle">{{ folder(file.path) }}</span></span>
              <span v-if="file.added != null" class="font-mono text-[0.6875rem] text-diff-add-fg">+{{ file.added }}</span>
              <span v-if="file.removed != null" class="font-mono text-[0.6875rem] text-diff-del-fg">−{{ file.removed }}</span>
              <span data-test="file-letter" class="w-3 text-center font-mono text-xs font-semibold" :class="LETTER_CLASS[file.status]">{{ file.status }}</span>
            </button>
            <div v-if="openFile === file.path" class="py-1">
              <p v-if="diffError" role="alert" class="m-0 text-xs text-diff-del-fg">{{ diffError }}</p>
              <p v-else-if="!diff" class="m-0 text-xs text-fg-muted">Carregando…</p>
              <template v-else>
                <p v-if="diff.notice" class="m-0 text-xs text-fg-muted">{{ diff.notice }}</p>
                <DiffLines :lines="diffFromUnified(diff.diff)" />
                <p v-if="diff.truncated" class="m-0 text-xs text-fg-muted">Diff cortado: o arquivo é grande demais.</p>
              </template>
            </div>
          </li>
        </ul>
        <p v-if="detail?.files_truncated" class="m-0 text-xs text-fg-muted">O commit tem mais arquivos do que a lista mostra.</p>
      </template>
    </div>
  </li>
</template>
