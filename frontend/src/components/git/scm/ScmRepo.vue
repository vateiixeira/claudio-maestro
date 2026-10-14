<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import ScmFileGroup from './ScmFileGroup.vue'
import ScmPrimaryButton from './ScmPrimaryButton.vue'
import ScmConfirm from './ScmConfirm.vue'
import IconArrowDown from '../../icons/IconArrowDown.vue'
import IconArrowUp from '../../icons/IconArrowUp.vue'
import IconChevron from '../../icons/IconChevron.vue'
import IconClose from '../../icons/IconClose.vue'
import { errorMessage, openInEditor } from '../../../api/http'
import { busyLabel } from '../../../git/busyLabel'
import { clearDraft, readDraft, writeDraft } from '../../../git/commitDraft'
import { runningLine, type Confirmation } from '../../../git/confirmation'
import { primaryAction, type PrimaryKind } from '../../../git/primaryAction'
import { repoLabel, syncCounts } from '../../../git/repoLabel'
import { runningSessionIn } from '../../../git/runningSession'
import { useGitDetailsStore } from '../../../stores/gitDetails'
import { useGitOpsStore } from '../../../stores/gitOps'
import { useProjectsStore } from '../../../stores/projects'
import { useSessionsStore } from '../../../stores/sessions'
import type { GitOpAnswer, GitOpKind, RepoDetails, RepoFile } from '../../../types/api'

const props = defineProps<{ projectId: number; repo: RepoDetails; collapseAll: number; startOpen: boolean }>()

const details = useGitDetailsStore()
const ops = useGitOpsStore()
const projects = useProjectsStore()
const sessions = useSessionsStore()

const open = ref(props.startOpen)
watch(() => props.collapseAll, () => { open.value = false })
watch(() => props.startOpen, (value) => { if (value) open.value = true })

const name = computed(() => repoLabel(props.repo, projects.byId(props.projectId)?.name))
const state = computed(() => props.repo.state ?? null)
const readOnly = computed(() => state.value?.read_only ?? null)
const sync = computed(() => syncCounts(props.repo))
const running = computed(() => runningSessionIn(sessions.all, props.repo.path))
const busyKind = computed(() => ops.busyFor(props.repo.path))
const busy = computed(() => (busyKind.value ? busyLabel(busyKind.value, props.repo) : null))
const error = computed(() => ops.errorFor(props.repo.path))
const showOutput = ref(false)
watch(error, () => { showOutput.value = false })
const revision = computed(() => details.revisionFor(props.projectId))
const branchName = computed(() => (props.repo.detached ? (props.repo.head ?? '') : (props.repo.branch ?? '')))
const dirty = computed(() => props.repo.files.length > 0)

const message = ref(readDraft(props.repo.path))
watch(message, (text) => writeDraft(props.repo.path, text))
const action = computed(() => primaryAction(props.repo, message.value))

const staged = computed(() => props.repo.files.filter((f) => f.status === 'staged'))
const changes = computed(() => props.repo.files.filter((f) => f.status !== 'staged'))

// Confirmation dialog: `ask` resolves with the answer.
const pending = ref<{ value: Confirmation; resolve: (ok: boolean) => void } | null>(null)
function ask(value: Confirmation): Promise<boolean> {
  return new Promise((resolve) => { pending.value = { value, resolve } })
}
function answer(ok: boolean): void {
  pending.value?.resolve(ok)
  pending.value = null
}
// Leaving the screen with the dialog open: whoever awaits `ask` must not wait forever.
onBeforeUnmount(() => answer(false))

function act(kind: GitOpKind, body: Record<string, unknown> = {}): Promise<GitOpAnswer | null> {
  return ops.run(props.projectId, props.repo.path, kind, body)
}

async function commit(): Promise<void> {
  if (action.value.kind !== 'commit' || action.value.disabled || busyKind.value) return
  const sent = message.value
  const done = await act('commit', { message: sent })
  // Typing went on while the commit ran: what is in the field now was not committed.
  if (done && message.value === sent) {
    message.value = ''
    clearDraft(props.repo.path)
  }
}

async function discard(files: RepoFile[]): Promise<void> {
  const paths = [...new Set(files.map((f) => f.path))]
  const one = paths.length === 1 ? files[0] : null
  const lines = one
    ? ['O arquivo volta ao último commit. Não dá para desfazer pelo app.']
    : ['Os arquivos voltam ao último commit. Não dá para desfazer pelo app.']
  if (files.some((f) => f.status === 'untracked')) lines.push('Num arquivo novo, ainda fora do git, descartar apaga o arquivo.')
  if (running.value) lines.unshift(runningLine('discard'))
  const ok = await ask({
    title: one ? 'Descartar alterações?' : `Descartar ${paths.length} alterações?`,
    confirmLabel: running.value ? 'Descartar mesmo assim' : 'Descartar',
    tone: 'danger',
    running: running.value,
    repoName: name.value,
    lines,
    file: one ? { path: one.path, kind: one.kind ?? 'M', added: one.added, removed: one.removed, untracked: one.status === 'untracked' } : undefined,
  })
  if (ok) await act('discard', { paths })
}

const editorError = ref<string | null>(null)
async function editor(file: RepoFile): Promise<void> {
  editorError.value = null
  try {
    await openInEditor(`${props.repo.path}/${file.path}`)
  } catch (e) {
    editorError.value = errorMessage(e)
  }
}

/** What the wide button does; a kind without a handler leaves the button off. */
const handlers: Partial<Record<PrimaryKind, () => void>> = {
  commit: () => void commit(),
}
function runPrimary(): void {
  handlers[action.value.kind]?.()
}

function onMessageKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.isComposing) {
    event.preventDefault()
    if (action.value.kind === 'commit') void commit()
    else runPrimary()
  }
}

const iconButton = 'flex size-6 items-center justify-center rounded text-fg-muted hover:bg-card hover:text-fg disabled:cursor-default disabled:opacity-50 disabled:hover:bg-transparent'

// For the tasks that fill this component further (branch menu, merge, conflicts, sync).
defineExpose({ ask, act, handlers })
</script>

<template>
  <li data-test="scm-repo" :data-repo="repo.path" class="flex flex-col">
    <div class="flex h-7 items-center gap-1.5 rounded pr-1 hover:bg-elevated">
      <button type="button" data-test="scm-repo-toggle" :aria-expanded="open" class="flex min-w-0 grow items-center gap-1.5 pl-1 text-left" @click="open = !open">
        <IconChevron :open="open" :size="12" class="text-fg-subtle" />
        <span class="truncate font-mono text-[0.8125rem] font-semibold text-fg">{{ name }}</span>
        <svg v-if="running" data-test="running-arc" :title="`${running.title} em execução aqui`" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" class="shrink-0 text-primary motion-safe:animate-spin" role="img" :aria-label="`${running.title} em execução aqui`"><title>{{ running.title }} em execução aqui</title><path d="M21 12a9 9 0 1 1-6.22-8.56" /></svg>
        <span v-if="readOnly" data-test="read-only-tag" class="ml-1 text-xs text-fg-subtle">só leitura</span>
      </button>
      <slot name="branch" :branch="branchName" :dirty="dirty">
        <span data-test="scm-branch" :title="repo.detached ? 'HEAD solto' : undefined" class="max-w-48 truncate px-1.5 font-mono text-xs text-fg-muted">{{ branchName }}{{ dirty ? '*' : '' }}</span>
      </slot>
      <span
        data-test="sync-counts"
        class="inline-flex shrink-0 items-center gap-1.5 font-mono text-xs"
        :role="sync.kind === 'diverged' ? 'img' : undefined"
        :aria-label="sync.kind === 'diverged' ? `${sync.behind} para baixar, ${sync.ahead} para subir` : undefined"
      >
        <span v-if="sync.kind === 'none'" class="text-fg-subtle">sem upstream</span>
        <span v-else-if="sync.kind === 'synced'" class="text-fg-subtle">em dia</span>
        <template v-else-if="sync.kind === 'diverged'">
          <span class="inline-flex items-center" :class="sync.behind > 0 ? 'text-info-soft' : 'text-fg-subtle'"><IconArrowDown :size="12" />{{ sync.behind }}</span>
          <span class="inline-flex items-center" :class="sync.ahead > 0 ? 'text-fg' : 'text-fg-subtle'"><IconArrowUp :size="12" />{{ sync.ahead }}</span>
        </template>
      </span>
      <template v-if="!repo.error">
        <button
          v-if="!readOnly"
          type="button"
          data-test="repo-commit"
          :class="iconButton"
          :disabled="!!busyKind || action.kind !== 'commit' || action.disabled"
          aria-label="Commitar"
          :title="action.kind === 'commit' && !action.disabled ? 'Commitar' : (action.reason ?? 'Commitar')"
          @click="commit"
        ><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12" /></svg></button>
        <button type="button" data-test="repo-refresh" :class="iconButton" :disabled="!!busyKind" aria-label="Atualizar" title="Reler o estado git" @click="details.load(projectId)">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a9 9 0 1 1-2.64-6.36" /><path d="M21 3v6h-6" /></svg>
        </button>
      </template>
    </div>

    <p v-if="repo.error" data-test="scm-repo-error" role="alert" class="m-0 pl-5 text-xs text-diff-del-fg">{{ repo.error }}</p>
    <div v-else-if="open" data-test="scm-body" class="flex flex-col gap-1.5 pt-1 pb-2 pl-5">
      <p v-if="readOnly" data-test="read-only-note" class="m-0 text-xs leading-normal text-fg-subtle">{{ readOnly }}</p>
      <template v-else>
        <slot name="merge-banner" />
        <input
          v-model="message"
          type="text"
          data-test="commit-message"
          :aria-label="`Mensagem do commit em ${name}`"
          :placeholder="`Mensagem (Ctrl+Enter commita em ${branchName})`"
          class="h-[26px] w-full rounded-md border border-line-strong bg-surface px-2 text-[0.8125rem] text-fg placeholder:text-fg-subtle focus:border-fg-muted focus:outline-none"
          @keydown="onMessageKeydown"
        >
        <ScmPrimaryButton :action="action" :busy="busy" :available="!!handlers[action.kind]" @run="runPrimary" />
        <p v-if="state?.has_hooks" data-test="hooks-note" class="m-0 text-xs text-fg-subtle">Este repositório tem hooks. O commit feito pelo app não os executa.</p>
        <p v-if="state?.gpgsign" data-test="gpg-note" class="m-0 text-xs text-fg-subtle">Seu git pede commits assinados. O commit feito pelo app sai sem assinatura.</p>
      </template>
      <div v-if="error" data-test="scm-error" role="alert" class="flex items-start gap-1.5 text-xs leading-normal text-diff-del-fg">
        <span class="min-w-0 grow">{{ error.message }}
          <button v-if="error.output" type="button" data-test="show-output" class="border-0 bg-transparent p-0 text-xs text-fg-muted underline" @click="showOutput = !showOutput">{{ showOutput ? 'Esconder saída do git' : 'Ver saída do git' }}</button>
        </span>
        <button type="button" data-test="dismiss-error" class="flex size-5 shrink-0 items-center justify-center rounded text-fg-muted hover:bg-card" aria-label="Fechar aviso" @click="ops.dismiss(repo.path)"><IconClose :size="12" /></button>
      </div>
      <pre v-if="error && showOutput" data-test="scm-error-output" class="m-0 max-h-48 overflow-auto rounded-md border border-line bg-bg p-2 font-mono text-[0.6875rem] whitespace-pre-wrap text-fg-muted">{{ error.output }}</pre>
      <p v-if="editorError" role="alert" class="m-0 text-xs text-diff-del-fg">{{ editorError }}</p>
      <slot name="groups" :revision="revision" :read-only="!!readOnly" :disabled="!!busyKind" :discard="discard" :editor="editor">
        <ScmFileGroup v-if="staged.length" :project-id="projectId" :repo="repo" group="staged" title="Preparados" :files="staged" :revision="revision" :read-only="!!readOnly" :disabled="!!busyKind" @stage="(p) => act('stage', { paths: p })" @unstage="(p) => act('unstage', { paths: p })" @discard="discard" @editor="editor" />
        <ScmFileGroup v-if="changes.length" :project-id="projectId" :repo="repo" group="changes" title="Alterações" :files="changes" :revision="revision" :read-only="!!readOnly" :disabled="!!busyKind" @stage="(p) => act('stage', { paths: p })" @unstage="(p) => act('unstage', { paths: p })" @discard="discard" @editor="editor" />
      </slot>
      <p v-if="repo.files_truncated" class="m-0 text-xs text-fg-muted">Há mais arquivos alterados do que a lista mostra.</p>
    </div>
    <ScmConfirm v-if="pending" :confirmation="pending.value" @confirm="answer(true)" @cancel="answer(false)" />
  </li>
</template>
