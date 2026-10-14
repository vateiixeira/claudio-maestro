<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import ScmFileGroup from './ScmFileGroup.vue'
import ScmPrimaryButton from './ScmPrimaryButton.vue'
import ScmConfirm from './ScmConfirm.vue'
import BranchMenu from './BranchMenu.vue'
import CreateBranchDialog from './CreateBranchDialog.vue'
import MergeBanner from './MergeBanner.vue'
import ScmRepoMenu from './ScmRepoMenu.vue'
import IconArrowDown from '../../icons/IconArrowDown.vue'
import IconArrowUp from '../../icons/IconArrowUp.vue'
import IconChevron from '../../icons/IconChevron.vue'
import IconClose from '../../icons/IconClose.vue'
import { compareBranch, errorMessage, openInEditor, sendMessage } from '../../../api/http'
import { busyLabel } from '../../../git/busyLabel'
import { conflictPrompt } from '../../../git/conflictPrompt'
import { clearDraft, readDraft, readMergeMessage, writeDraft, writeMergeMessage } from '../../../git/commitDraft'
import { runningLine, type Confirmation } from '../../../git/confirmation'
import { primaryAction, type PrimaryKind } from '../../../git/primaryAction'
import { repoLabel, syncCounts } from '../../../git/repoLabel'
import { runningSessionIn } from '../../../git/runningSession'
import { useGitDetailsStore } from '../../../stores/gitDetails'
import { useGitOpsStore } from '../../../stores/gitOps'
import { useProjectsStore } from '../../../stores/projects'
import { useSessionsStore } from '../../../stores/sessions'
import { useMediaQuery } from '../../../useMediaQuery'
import type { BranchRef, GitOpAnswer, GitOpKind, RepoDetails, RepoFile } from '../../../types/api'

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
// Between choosing the branch and the dialog, while the commits that would come in are counted.
const preparingMerge = ref(false)
const busy = computed(() => (busyKind.value ? busyLabel(busyKind.value, props.repo) : preparingMerge.value ? 'Mesclando…' : null))
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
// Files in conflict never go through the plain stage and discard: `git add` would mark them as
// resolved even with the markers still in.
const conflictFiles = computed(() => props.repo.files.filter((f) => f.status === 'conflict'))
const changes = computed(() => props.repo.files.filter((f) => f.status !== 'staged' && f.status !== 'conflict'))
const merging = computed(() => state.value?.merging === true)
const conflictLabels = computed(() => ({ ours: branchName.value, theirs: state.value?.merge_branch ?? '' }))
const changedPaths = computed(() => new Set(props.repo.files.map((f) => f.path)).size)

// The merge message git prepared fills the field when a merge starts, and leaves with it. What
// the app put there is kept apart from the draft, so that it can be told from what the person
// typed even after the component was mounted again.
watch(merging, (now) => {
  if (now) {
    if (message.value.trim()) return
    const text = state.value?.merge_message ?? `Merge branch '${state.value?.merge_branch ?? ''}'`
    writeMergeMessage(props.repo.path, text)
    message.value = text
    return
  }
  const known = readMergeMessage(props.repo.path)
  if (known === null) return
  if (message.value === known) message.value = ''
  writeMergeMessage(props.repo.path, null)
}, { immediate: true })

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
    writeMergeMessage(props.repo.path, null)
  }
}

async function discard(files: RepoFile[]): Promise<void> {
  const paths = [...new Set(files.map((f) => f.path))]
  const one = paths.length === 1 ? files[0] : null
  const lines = one
    ? ['O arquivo volta ao último commit. Não dá para desfazer pelo app.']
    : ['Os arquivos voltam ao último commit. Não dá para desfazer pelo app.']
  if (merging.value) lines.push(one ? 'Também desfaz o que o merge trouxe para este arquivo.' : 'Também desfaz o que o merge trouxe para estes arquivos.')
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

const router = useRouter()
const wideScreen = useMediaQuery('(min-width: 1200px)')
const chip = ref<HTMLButtonElement | null>(null)
const menu = ref<'switch' | 'merge' | null>(null)
const creating = ref<{ initial: string; error: string | null } | null>(null)

/** Back to the branch button after a menu or dialog closes without acting. */
function focusChip(): void {
  void nextTick(() => chip.value?.focus())
}
function closeMenu(restoreFocus = true): void {
  menu.value = null
  if (restoreFocus) focusChip()
}
function closeCreating(): void {
  creating.value = null
  focusChip()
}

async function switchTo(branch: BranchRef): Promise<void> {
  menu.value = null
  const target = branch.ref.startsWith('refs/remotes/') ? branch.name.slice(branch.name.indexOf('/') + 1) : branch.name
  if (running.value) {
    const ok = await ask({
      title: `Trocar para ${target}?`, confirmLabel: 'Trocar mesmo assim', tone: 'warn',
      running: running.value, repoName: name.value, lines: [runningLine('switch')],
    })
    if (!ok) return focusChip()
  }
  await act('switch', { ref: branch.ref })
}

async function mergeIn(branch: BranchRef): Promise<void> {
  menu.value = null
  if (preparingMerge.value || busyKind.value) return
  let incoming: number | null = null
  preparingMerge.value = true
  try {
    incoming = (await compareBranch(props.projectId, props.repo.path, branch.ref)).incoming
  } catch {
    incoming = null
  } finally {
    preparingMerge.value = false
  }
  const count = incoming == null ? `Entram os commits de ${branch.name}.`
    : incoming === 0 ? `Não entra nenhum commit de ${branch.name}: ${branchName.value} já tem tudo.`
    : incoming === 1 ? `Entra 1 commit de ${branch.name}.` : `Entram ${incoming} commits de ${branch.name}.`
  const lines = [
    `${count} Se as duas branches mexeram nas mesmas linhas, o merge para em conflito e o bloco mostra o que resolver.`,
    `${branchName.value} continua sendo a branch atual.`,
    'Nada é enviado ao remoto.',
  ]
  if (running.value) lines.unshift(runningLine('merge'))
  const ok = await ask({
    title: `Mesclar ${branch.name} em ${branchName.value}?`,
    confirmLabel: running.value ? 'Mesclar mesmo assim' : 'Mesclar',
    tone: running.value ? 'warn' : 'primary',
    running: running.value, repoName: name.value, lines,
  })
  if (!ok) return focusChip()
  const done = await act('merge', { ref: branch.ref })
  if (done) open.value = true
}

async function createBranch(newName: string): Promise<void> {
  if (!creating.value) return
  creating.value.error = null
  const done = await act('branch', { name: newName })
  if (done) {
    creating.value = null
    return
  }
  // The error belongs to the dialog, not to the repository's line.
  if (creating.value) creating.value.error = ops.errorFor(props.repo.path)?.message ?? null
  ops.dismiss(props.repo.path)
}

async function abortMerge(): Promise<void> {
  const ok = await ask({
    title: 'Abortar o merge?', confirmLabel: 'Abortar merge', tone: 'danger', running: running.value, repoName: name.value,
    lines: ['Os arquivos voltam a como estavam antes do merge. O que você já resolveu se perde.', 'Não dá para desfazer pelo app.'],
  })
  if (ok && await act('merge-abort')) {
    message.value = ''
    clearDraft(props.repo.path)
    writeMergeMessage(props.repo.path, null)
  }
}

async function finishMerge(): Promise<void> {
  if (action.value.kind !== 'merge-continue' || action.value.disabled || busyKind.value) return
  if (await act('merge-continue', { message: message.value })) {
    message.value = ''
    clearDraft(props.repo.path)
    writeMergeMessage(props.repo.path, null)
  }
}

const asking = ref(false)
const claudeError = ref<string | null>(null)
// The session made for this merge: a failed send is retried in it, not in a new one.
let askSessionId: string | null = null
watch(merging, (now) => {
  if (!now) {
    claudeError.value = null
    askSessionId = null
  }
})
async function askClaude(): Promise<void> {
  asking.value = true
  claudeError.value = null
  try {
    askSessionId ??= (await sessions.create(props.projectId)).session_id
    const id = askSessionId
    await sendMessage(id, conflictPrompt(props.repo, name.value))
    await router.push(wideScreen.value
      ? { name: 'project', params: { id: String(props.projectId) }, query: { sessao: id } }
      : { name: 'session', params: { id } })
  } catch (e) {
    claudeError.value = errorMessage(e)
  } finally {
    asking.value = false
  }
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

const moreOpen = ref(false)
const moreButton = ref<HTMLButtonElement | null>(null)
const hasUpstream = computed(() => props.repo.upstream != null)
/** Why Baixar or Enviar is off, in the same words as Mesclar; null when it is on. */
function networkReason(verb: 'baixar' | 'enviar', nothing: string): string | null {
  if (readOnly.value) return readOnly.value
  if (merging.value) return `Conclua ou aborte o merge antes de ${verb}`
  if (props.repo.detached) return `O HEAD está solto: não há branch para ${verb}.`
  if (!hasUpstream.value) {
    return (state.value?.remotes.length ?? 0) > 0 ? 'Esta branch não acompanha nenhuma branch remota. Use Publicar.' : 'Este repositório não tem remoto.'
  }
  if (verb === 'baixar' && state.value?.no_merge) return state.value.no_merge
  return (verb === 'baixar' ? (props.repo.behind ?? 0) : (props.repo.ahead ?? 0)) > 0 ? null : nothing
}
const pullReason = computed(() => networkReason('baixar', 'Nada para baixar'))
const pushReason = computed(() => networkReason('enviar', 'Nada para enviar'))
const canPull = computed(() => pullReason.value === null)
const canPush = computed(() => pushReason.value === null)
const pullTitle = computed(() => pullReason.value ?? 'Baixar (pull)')
const pushTitle = computed(() => pushReason.value ?? 'Enviar (push)')
const syncTitle = computed(() => (sync.value.kind === 'diverged' ? `${sync.value.behind} para baixar, ${sync.value.ahead} para subir` : undefined))

/** Pull and sync change the files: a running session is asked about first. */
async function bringIn(kind: 'pull' | 'sync'): Promise<void> {
  if (busyKind.value) return
  if (running.value) {
    const ok = await ask({
      title: kind === 'pull' ? 'Baixar agora?' : 'Sincronizar agora?',
      confirmLabel: kind === 'pull' ? 'Baixar mesmo assim' : 'Sincronizar mesmo assim',
      tone: 'warn', running: running.value, repoName: name.value, lines: [runningLine(kind)],
    })
    if (!ok) return
  }
  const done = await act(kind)
  if (done?.conflicts) open.value = true
}

async function pushNow(): Promise<void> {
  if (!busyKind.value) await act('push')
}

async function publishNow(): Promise<void> {
  if (!busyKind.value && !action.value.disabled) await act('publish')
}

/** Back to the "…" button after the menu closes. */
function closeMore(restoreFocus = true): void {
  moreOpen.value = false
  if (restoreFocus) void nextTick(() => moreButton.value?.focus())
}

async function fetchNow(): Promise<void> {
  closeMore()
  await act('fetch-repo')
}

async function copyPath(): Promise<void> {
  closeMore()
  try {
    await navigator.clipboard.writeText(props.repo.path)
  } catch {
    // Without clipboard access nothing is copied.
  }
}

function abortFromMenu(): void {
  closeMore()
  void abortMerge()
}

/** What the wide button does; a kind without a handler leaves the button off. */
const handlers: Partial<Record<PrimaryKind, () => void>> = {
  commit: () => void commit(),
  'merge-continue': () => void finishMerge(),
  pull: () => void bringIn('pull'),
  sync: () => void bringIn('sync'),
  push: () => void pushNow(),
  publish: () => void publishNow(),
}
function runPrimary(): void {
  // Ctrl+Enter reaches here too: an action that is off (or busy) does nothing, of any kind.
  if (action.value.disabled || busyKind.value) return
  handlers[action.value.kind]?.()
}

function onMessageKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.isComposing) {
    event.preventDefault()
    // Only the commit and the end of a merge: pull, push, sync and publish go through the
    // network, and a shortcut typed into the message field must not reach out to the remote.
    if (action.value.kind === 'commit' || action.value.kind === 'merge-continue') runPrimary()
  }
}

// The tooltips of the icons that can be off say why. An action in progress comes after the
// read-only reason, which does not go away when the action ends.
const branchTitle = computed(() => {
  if (readOnly.value) return readOnly.value
  if (merging.value) return 'Conclua ou aborte o merge antes de trocar de branch'
  if (busy.value) return busy.value
  return 'Trocar de branch'
})
const mergeTitle = computed(() => {
  if (readOnly.value) return readOnly.value
  if (busy.value) return busy.value
  if (merging.value) return 'Já há um merge em andamento'
  if (state.value?.no_merge) return state.value.no_merge
  if (!props.repo.head) return 'Ainda não há commits.'
  return `Mesclar uma branch em ${branchName.value}`
})
const commitTitle = computed(() => {
  if (readOnly.value) return readOnly.value
  if (busy.value) return busy.value
  if (action.value.kind === 'merge-continue') return 'Conclua o merge com Concluir merge'
  if (action.value.kind !== 'commit') return 'Nada para commitar'
  return action.value.disabled ? (action.value.reason ?? 'Commitar') : 'Commitar'
})

const iconButton = 'flex size-6 items-center justify-center rounded text-fg-muted hover:bg-card hover:text-fg disabled:cursor-default disabled:opacity-50 disabled:hover:bg-transparent'

// For the tasks that fill this component further (branch menu, merge, conflicts, sync).
defineExpose({ ask, act, handlers })
</script>

<template>
  <li data-test="scm-repo" :data-repo="repo.path" class="relative flex flex-col">
    <div class="flex h-7 items-center gap-1.5 rounded pr-1 hover:bg-elevated">
      <button type="button" data-test="scm-repo-toggle" :aria-expanded="open" class="flex min-w-0 grow items-center gap-1.5 pl-1 text-left" @click="open = !open">
        <IconChevron :open="open" :size="12" class="text-fg-subtle" />
        <span class="truncate font-mono text-[0.8125rem] font-semibold text-fg">{{ name }}</span>
        <svg v-if="running" data-test="running-arc" :title="`${running.title} em execução aqui`" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" class="shrink-0 text-primary motion-safe:animate-spin" role="img" :aria-label="`${running.title} em execução aqui`"><title>{{ running.title }} em execução aqui</title><path d="M21 12a9 9 0 1 1-6.22-8.56" /></svg>
        <span v-if="readOnly" data-test="read-only-tag" class="ml-1 text-xs text-fg-subtle">só leitura</span>
      </button>
      <slot name="branch" :branch="branchName" :dirty="dirty">
        <button
          ref="chip"
          type="button"
          data-test="branch-chip"
          :disabled="!!readOnly || !!busyKind || preparingMerge || merging"
          :title="branchTitle"
          class="max-w-48 truncate rounded px-1.5 font-mono text-xs text-fg-muted hover:bg-card hover:text-fg disabled:hover:bg-transparent"
          @click="menu = 'switch'"
        ><span data-test="scm-branch" :title="repo.detached ? 'HEAD solto' : undefined">{{ branchName }}{{ dirty ? '*' : '' }}</span></button>
        <span v-if="merging" data-test="merging-tag" class="flex shrink-0 items-center gap-1 text-xs text-secondary"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /><path d="M12 9v4" /><path d="M12 17h.01" /></svg>merge em andamento</span>
      </slot>
      <span
        data-test="sync-counts"
        class="inline-flex shrink-0 items-center gap-1.5 font-mono text-xs"
        :role="sync.kind === 'diverged' ? 'img' : undefined"
        :aria-label="sync.kind === 'diverged' ? `${sync.behind} para baixar, ${sync.ahead} para subir` : undefined"
        :title="syncTitle"
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
          type="button"
          data-test="repo-merge"
          :class="iconButton"
          :disabled="!!readOnly || !!busyKind || preparingMerge || merging || !!state?.no_merge || !repo.head"
          aria-label="Mesclar uma branch"
          :title="mergeTitle"
          @click="menu = 'merge'"
        ><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="18" cy="18" r="3" /><circle cx="6" cy="6" r="3" /><path d="M6 21V9a9 9 0 0 0 9 9" /></svg></button>
        <button
          type="button"
          data-test="repo-commit"
          :class="iconButton"
          :disabled="!!readOnly || !!busyKind || action.kind !== 'commit' || action.disabled"
          aria-label="Commitar"
          :title="commitTitle"
          @click="commit"
        ><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12" /></svg></button>
        <button
          type="button"
          data-test="repo-pull"
          :class="iconButton"
          :disabled="!!busyKind || !canPull"
          aria-label="Baixar"
          :title="pullTitle"
          @click="bringIn('pull')"
        ><IconArrowDown :size="14" /></button>
        <button
          type="button"
          data-test="repo-push"
          :class="iconButton"
          :disabled="!!busyKind || !canPush"
          aria-label="Enviar"
          :title="pushTitle"
          @click="pushNow"
        ><IconArrowUp :size="14" /></button>
        <button type="button" data-test="repo-refresh" :class="iconButton" :disabled="!!busyKind" aria-label="Atualizar" title="Reler o estado git" @click="details.load(projectId)">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a9 9 0 1 1-2.64-6.36" /><path d="M21 3v6h-6" /></svg>
        </button>
        <button ref="moreButton" type="button" data-test="repo-more" :class="iconButton" aria-haspopup="menu" :aria-expanded="moreOpen" aria-label="Mais ações" title="Mais ações" @click="moreOpen = !moreOpen">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="19" cy="12" r="1.6" /></svg>
        </button>
      </template>
    </div>

    <BranchMenu
      v-if="menu"
      :project-id="projectId"
      :repo="repo"
      :mode="menu"
      :can-merge="!state?.no_merge && !!repo.head"
      @close="(restore) => closeMenu(restore !== false)"
      @switch="switchTo"
      @merge="mergeIn"
      @create="(initial) => { menu = null; creating = { initial, error: null } }"
    />

    <ScmRepoMenu v-if="moreOpen" :merging="merging && !readOnly" :can-fetch="hasUpstream && !busyKind" @close="(restore) => closeMore(restore !== false)" @fetch="fetchNow" @copy="copyPath" @abort="abortFromMenu" />

    <!-- Outside the body: the error of a fetch must show with the repository collapsed too. -->
    <div v-if="error" data-test="scm-error-area" class="flex flex-col gap-1.5 pt-1 pl-5">
      <div data-test="scm-error" role="alert" class="flex items-start gap-1.5 text-xs leading-normal text-diff-del-fg">
        <span class="min-w-0 grow">{{ error.message }}
          <button v-if="error.output" type="button" data-test="show-output" class="border-0 bg-transparent p-0 text-xs text-fg-muted underline" @click="showOutput = !showOutput">{{ showOutput ? 'Esconder saída do git' : 'Ver saída do git' }}</button>
        </span>
        <button type="button" data-test="dismiss-error" class="flex size-5 shrink-0 items-center justify-center rounded text-fg-muted hover:bg-card" aria-label="Fechar aviso" @click="ops.dismiss(repo.path)"><IconClose :size="12" /></button>
      </div>
      <pre v-if="showOutput" data-test="scm-error-output" class="m-0 max-h-48 overflow-auto rounded-md border border-line bg-bg p-2 font-mono text-[0.6875rem] whitespace-pre-wrap text-fg-muted">{{ error.output }}</pre>
    </div>

    <p v-if="repo.error" data-test="scm-repo-error" role="alert" class="m-0 pl-5 text-xs text-diff-del-fg">{{ repo.error }}</p>
    <div v-else-if="open" data-test="scm-body" class="flex flex-col gap-1.5 pt-1 pb-2 pl-5">
      <p v-if="readOnly" data-test="read-only-note" class="m-0 text-xs leading-normal text-fg-subtle">{{ readOnly }}</p>
      <template v-else>
        <slot name="merge-banner">
          <MergeBanner v-if="merging" :repo="repo" :busy="!!busyKind" :asking="asking" @ask="askClaude" @abort="abortMerge" />
          <p v-if="claudeError" role="alert" class="m-0 text-xs text-diff-del-fg">{{ claudeError }}</p>
        </slot>
        <input
          v-model="message"
          type="text"
          data-test="commit-message"
          :aria-label="`Mensagem do commit em ${name}`"
          :placeholder="merging ? 'Mensagem do commit do merge' : `Mensagem (Ctrl+Enter commita em ${branchName})`"
          class="h-[26px] w-full rounded-md border border-line-strong bg-surface px-2 text-[0.8125rem] text-fg placeholder:text-fg-subtle focus:border-fg-muted focus:outline-none"
          @keydown="onMessageKeydown"
        >
        <ScmPrimaryButton :action="action" :busy="busy" :available="!!handlers[action.kind]" @run="runPrimary" />
        <p v-if="state?.has_hooks" data-test="hooks-note" class="m-0 text-xs text-fg-subtle">Este repositório tem hooks. O commit feito pelo app não os executa.</p>
        <p v-if="state?.gpgsign" data-test="gpg-note" class="m-0 text-xs text-fg-subtle">Seu git pede commits assinados. O commit feito pelo app sai sem assinatura.</p>
      </template>
      <p v-if="editorError" role="alert" class="m-0 text-xs text-diff-del-fg">{{ editorError }}</p>
      <slot name="groups" :revision="revision" :read-only="!!readOnly" :disabled="!!busyKind" :discard="discard" :editor="editor">
        <ScmFileGroup v-if="conflictFiles.length" :project-id="projectId" :repo="repo" group="conflict" title="Em conflito" :files="conflictFiles" :revision="revision" :read-only="!!readOnly" :disabled="!!busyKind" :conflict-labels="conflictLabels" @editor="editor">
          <template #group-actions />
          <template v-if="!merging" #note>
            <p data-test="conflict-outside-note" class="m-0 pl-5 text-xs leading-normal text-fg-subtle">Há conflitos fora de um merge. Resolva pelo terminal.</p>
          </template>
          <template #file-actions="{ file }">
            <button v-if="merging" type="button" data-test="file-resolve" class="flex size-[22px] items-center justify-center rounded text-fg-muted hover:bg-card hover:text-fg disabled:opacity-50" :disabled="!!busyKind" aria-label="Marcar como resolvido" title="Marcar como resolvido" @click="act('resolve', { paths: [file.path] })">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12" /></svg>
            </button>
          </template>
        </ScmFileGroup>
        <!-- During a merge, what is staged is the merge itself: unstaging or discarding it would undo the resolution. -->
        <ScmFileGroup v-if="staged.length" :project-id="projectId" :repo="repo" :group="merging ? 'ready' : 'staged'" :title="merging ? 'Prontos para o merge' : 'Preparados'" :files="staged" :revision="revision" :read-only="!!readOnly" :disabled="!!busyKind" @stage="(p) => act('stage', { paths: p })" @unstage="(p) => act('unstage', { paths: p })" @discard="discard" @editor="editor">
          <template v-if="merging" #group-actions />
          <template v-if="merging" #file-actions />
        </ScmFileGroup>
        <ScmFileGroup v-if="changes.length" :project-id="projectId" :repo="repo" group="changes" title="Alterações" :files="changes" :revision="revision" :read-only="!!readOnly" :disabled="!!busyKind" @stage="(p) => act('stage', { paths: p })" @unstage="(p) => act('unstage', { paths: p })" @discard="discard" @editor="editor" />
      </slot>
      <p v-if="repo.files_truncated" class="m-0 text-xs text-fg-muted">Há mais arquivos alterados do que a lista mostra.</p>
    </div>
    <ScmConfirm v-if="pending" :confirmation="pending.value" @confirm="answer(true)" @cancel="answer(false)" />
    <CreateBranchDialog
      v-if="creating"
      :from="branchName"
      :sha="repo.head"
      :changes="changedPaths"
      :initial="creating.initial"
      :error="creating.error"
      :busy="busyKind === 'branch'"
      @submit="createBranch"
      @cancel="closeCreating"
    />
  </li>
</template>
