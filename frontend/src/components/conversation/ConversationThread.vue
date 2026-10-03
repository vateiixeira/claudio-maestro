<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, provide, reactive, ref, watch } from 'vue'
import { SESSION_ID_KEY, useChangesPanelStore } from '../../stores/changesPanel'
import { ApiError, errorMessage, markSessionSeen } from '../../api/http'
import { useEventSocket } from '../../api/socket'
import ConversationBlock from './ConversationBlock.vue'
import MessageComposer from './MessageComposer.vue'
import PermissionCard from './PermissionCard.vue'
import PlanCard from './PlanCard.vue'
import QuestionCard from './QuestionCard.vue'
import RailNode from './RailNode.vue'
import { railAlign } from '../../conversation/railAlign'
import SubagentStrip from './SubagentStrip.vue'
import UserMessage from './UserMessage.vue'
import { deriveSubagents, stripSubagents, SUBAGENT_FOCUS_KEY, waitingText, type SubagentFocus } from '../../conversation/subagents'
import { buildTurns, nodeKind, summaryText, tidyThinking, turnSummary } from '../../conversation/turns'
import { groupNodeKind, workStatus } from '../../conversation/work'
import WorkBlock from './WorkBlock.vue'
import SessionControls from '../session/SessionControls.vue'
import { useConversationStore } from '../../stores/conversation'
import { useProjectsStore } from '../../stores/projects'
import type { ConversationItem, ToolItem } from '../../types/conversation'
import { isBareShortcut } from '../../keyboardShortcutGuard'

const props = withDefaults(defineProps<{ id: string; visible?: boolean }>(), { visible: true })
const emit = defineEmits<{ missing: [] }>()

const conversations = useConversationStore()
const changesPanel = useChangesPanelStore()
const projects = useProjectsStore()
const socket = useEventSocket()

const loadError = ref<string | null>(null)
// Something arrived while the user was reading above: 'prompt' (needs them) outranks 'news'.
const unseen = ref<'news' | 'prompt' | null>(null)
const conv = computed(() => conversations.get(props.id))
const project = computed(() => (conv.value?.projectId != null ? projects.byId(conv.value.projectId) : undefined))
// The project's folder was deleted or moved: nothing that runs in it can work.
const unavailableReason = computed(() =>
  project.value && !project.value.available
    ? 'A pasta do projeto não existe mais. Restaure a pasta para voltar a enviar mensagens.'
    : null,
)

// "Ver alterações" in an edit card opens the changes panel for this session.
provide(SESSION_ID_KEY, computed(() => props.id))

// Loads in flight; "Tentar de novo" is aria-disabled (it keeps keyboard focus) while any is out.
const reloads = ref(0)
const reloading = computed(() => reloads.value > 0)
let unmounted = false
onBeforeUnmount(() => { unmounted = true })

async function reload() {
  const id = props.id
  reloads.value++
  try {
    const loaded = await conversations.load(id)
    // Left the conversation while it loaded: the store dropped the answer, nothing to show or mark.
    if (unmounted || id !== props.id || !loaded) return
    loadError.value = null
    markSeenSoon()
  } catch (e) {
    if (unmounted || id !== props.id) return
    if (e instanceof ApiError && e.status === 404) {
      emit('missing')
      return
    }
    loadError.value = errorMessage(e)
  } finally {
    reloads.value--
  }
}

// Tells the backend the user has looked at this session: after loading, when the
// conversation gets focus and when new items arrive, but only while it is visible.
const SEEN_DELAY = 300
let seenTimer: ReturnType<typeof setTimeout> | null = null
const canSee = () => props.visible && document.visibilityState !== 'hidden'
function cancelSeen() {
  if (seenTimer) clearTimeout(seenTimer)
  seenTimer = null
}
function markSeenSoon() {
  if (!canSee()) return
  cancelSeen()
  const id = props.id
  seenTimer = setTimeout(() => {
    seenTimer = null
    if (!canSee() || id !== props.id) return
    markSessionSeen(id).catch(() => {
      // Not worth bothering the user; the next focus or item tries again.
    })
  }, SEEN_DELAY)
}
watch(() => conv.value?.items.length, (length, before) => {
  if (length !== undefined && before !== undefined && length > before) markSeenSoon()
})
// A turn can end by updating existing items only; its result still counts as news.
watch(() => conv.value?.lastResult, (result, before) => {
  if (result && result !== before) markSeenSoon()
})
watch(() => props.visible, (visible) => (visible ? markSeenSoon() : cancelSeen()))
onBeforeUnmount(cancelSeen)

// Leaving a conversation drops what the store kept of it: the next visit starts from
// its snapshot (no stale turn result or decision card), and its images and diff go.
function leave(id: string) {
  conversations.forget(id)
  if (changesPanel.sessionId === id) changesPanel.close()
}

let offs: Array<() => void> = []
watch(
  () => props.id,
  (id, previous) => {
    offs.forEach((off) => off())
    if (previous !== undefined && previous !== id) leave(previous)
    offs = [
      socket.onSession(id, (event) => conversations.receive(event)),
      // Every opening, the first included: events between the snapshot and it were lost.
      socket.onOpen(() => void reload()),
    ]
    loadError.value = null
    unseen.value = null
    void reload()
  },
  { immediate: true },
)
onBeforeUnmount(() => {
  offs.forEach((off) => off())
  leave(props.id)
})

// Items with a parent tool are shown inside that tool's block (subagent card or indent).
const tree = computed(() => {
  const items = conv.value?.items ?? []
  const toolIds = new Set(items.flatMap((i) => (i.type === 'tool' ? [i.tool_use_id] : [])))
  const children = new Map<string, ConversationItem[]>()
  const top: ConversationItem[] = []
  for (const item of items) {
    const parent = 'parent_tool_use_id' in item ? item.parent_tool_use_id : null
    if (parent && toolIds.has(parent)) {
      const list = children.get(parent) ?? []
      list.push(item)
      children.set(parent, list)
    } else top.push(item)
  }
  // Inside a subagent the thinking is tidied the same way as in the turns.
  for (const [parent, list] of children) children.set(parent, tidyThinking(list))
  return { top, childrenOf: (toolUseId: string) => children.get(toolUseId) ?? [] }
})
const rows = computed(() => tree.value.top)
const sessionActive = computed(() => conv.value?.state === 'running' || conv.value?.state === 'awaiting_decision')
// Subagents and background commands still running, in conversation order. When the main turn
// is over, these are what the session is still waiting for.
const backgroundRunning = computed(() =>
  deriveSubagents(conv.value?.items ?? [], sessionActive.value).filter((entry) => entry.status === 'running'),
)
const waitingLabel = computed(() => waitingText(backgroundRunning.value))
const turns = computed(() => {
  const list = buildTurns(rows.value)
  // A pending decision or a connecting session is still inside the turn.
  const running = sessionActive.value || conv.value?.state === 'connecting'
  return list.map((turn, index) => {
    const last = index === list.length - 1
    const done = !last || !running
    // Over for the main turn, but not for the background work it started.
    const waiting = done && last && backgroundRunning.value.length > 0
    let summary = done && !waiting ? summaryText(turnSummary(turn, tree.value.childrenOf)) : ''
    if (done && !waiting && last && resultParts.value.length) summary = [summary, ...resultParts.value].join(' · ')
    return { turn, done, last, waiting, summary, failed: done && !waiting && last && resultFailed.value }
  })
})
// Last finished reply of the assistant, for the polite live region.
const announcement = computed(() => {
  const items = conv.value?.items ?? []
  for (let i = items.length - 1; i >= 0; i--) {
    const item = items[i]!
    if (item.type !== 'text') continue
    if (item.streaming || ('parent_tool_use_id' in item && item.parent_tool_use_id)) return ''
    return `Resposta concluída: ${item.text.slice(0, 300)}`
  }
  return ''
})
const taskList = computed(() => conversations.taskList(props.id))
// The actions that wait for the user: the tool of each pending request and the subagents it runs inside.
const waitingIds = computed(() => {
  const prompts = conv.value?.prompts ?? []
  const ids = new Set<string>()
  if (!prompts.length) return ids
  const items = conv.value?.items ?? []
  const byToolUse = new Map(items.flatMap((i) => (i.type === 'tool' ? [[i.tool_use_id, i] as const] : [])))
  for (const prompt of prompts) {
    for (let id = prompt.tool_use_id; id && !ids.has(id); ) {
      ids.add(id)
      id = byToolUse.get(id)?.parent_tool_use_id
    }
  }
  return ids
})

// Strip above the message field: the current subagents while any of them runs.
const subagentEntries = computed(() => stripSubagents(deriveSubagents(conv.value?.items ?? [], sessionActive.value)))
// The card the user picked in the strip: opened, marked for a moment and scrolled to.
const HIGHLIGHT_MS = 2000
const subagentFocus = ref<SubagentFocus | null>(null)
provide(SUBAGENT_FOCUS_KEY, subagentFocus)
let focusTimer: ReturnType<typeof setTimeout> | null = null
onBeforeUnmount(() => { if (focusTimer) clearTimeout(focusTimer) })
async function goToSubagent(id: string) {
  const items = conv.value?.items ?? []
  // The subagent cards it sits inside must open too.
  const byToolUse = new Map(items.flatMap((i) => (i.type === 'tool' ? [[i.tool_use_id, i] as const] : [])))
  const path: string[] = [id]
  for (let cur = items.find((i) => i.id === id); cur && 'parent_tool_use_id' in cur && cur.parent_tool_use_id; ) {
    const parent = byToolUse.get(cur.parent_tool_use_id)
    if (!parent || path.includes(parent.id)) break
    path.push(parent.id)
    cur = parent
  }
  if (focusTimer) clearTimeout(focusTimer)
  subagentFocus.value = null
  await nextTick()
  subagentFocus.value = { id, path }
  await nextTick()
  const card = Array.from(scroller.value?.querySelectorAll<HTMLElement>('[data-subagent-id]') ?? []).find((el) => el.dataset.subagentId === id)
  if (card) {
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    card.scrollIntoView?.({ behavior: reduce ? 'auto' : 'smooth', block: 'center' })
    card.focus({ preventScroll: true })
  }
  focusTimer = setTimeout(() => { subagentFocus.value = null }, HIGHLIGHT_MS)
}
// Open/closed chosen by the user per work block (by id); unset follows `blockOpen`.
const groupChoice = reactive(new Map<string, boolean>())
// By default a block is open while its turn runs, when one of its actions failed (the row opens by itself)
// and when it holds one action only; a finished turn folds the rest into the header.
function blockOpen(entry: { id: string; items: ToolItem[] }, done: boolean): boolean {
  return groupChoice.get(entry.id)
    ?? (!done || entry.items.length === 1 || entry.items.some((item) => workStatus(item, sessionActive.value) === 'error'))
}

// Duration and cost of the last turn, shown in its end line; its error is shown apart, in red.
const resultParts = computed(() => {
  const result = conv.value?.lastResult
  if (!result) return []
  const parts: string[] = []
  if (result.duration_ms != null) {
    parts.push(`${(result.duration_ms / 1000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} s`)
  }
  if (result.total_cost_usd != null) {
    parts.push(`US$ ${result.total_cost_usd.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`)
  }
  return parts
})
const resultFailed = computed(() => conv.value?.lastResult?.is_error === true)

// Follows the end of the conversation only while the user is already there.
const scroller = ref<HTMLElement | null>(null)
const atBottom = ref(true)
// Set when the user sends a message from the composer: the user item that follows is their own, not news.
const OWN_SEND_WINDOW_MS = 5000
let ownSendAt = 0
const PROMPT_CARD = '[data-prompt-card]'
const jumpLabel = computed(() => (unseen.value === 'prompt' && (conv.value?.prompts.length ?? 0) > 0 ? 'Pedido abaixo' : 'Novidades abaixo'))
function jumpToEnd() {
  const el = scroller.value
  if (!el) return
  const toPrompt = jumpLabel.value === 'Pedido abaixo'
  unseen.value = null
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  if (el.scrollTo) el.scrollTo({ top: el.scrollHeight, behavior: reduce ? 'auto' : 'smooth' })
  else el.scrollTop = el.scrollHeight
  // Whoever jumped for a request is sent to it: keyboard and screen reader users land on the card.
  if (toPrompt) el.querySelector<HTMLElement>(PROMPT_CARD)?.focus({ preventScroll: true })
}
function onScroll() {
  const el = scroller.value
  if (!el) return
  atBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 48
  if (atBottom.value) unseen.value = null
  scheduleTurnUpdate()
}

// Sticky turn bar: the current turn is the last one whose start is above the bar.
const TURN_BAR_HEIGHT = 44
const currentTurn = ref(0)
const turnAnchors = () => Array.from(scroller.value?.querySelectorAll<HTMLElement>('[data-turn-anchor]') ?? [])
let turnFrame: number | null = null
let turnPending = false
function scheduleTurnUpdate() {
  if (turnPending) return
  turnPending = true
  turnFrame = requestAnimationFrame(() => {
    turnPending = false
    turnFrame = null
    updateCurrentTurn()
  })
  if (!turnPending) turnFrame = null
}
onBeforeUnmount(() => { if (turnFrame !== null) cancelAnimationFrame(turnFrame) })
function updateCurrentTurn() {
  const el = scroller.value
  if (!el) return
  // At the end (same rule as the auto-scroll), the last turn is the current one.
  if (atBottom.value) {
    currentTurn.value = Math.max(turns.value.length - 1, 0)
    return
  }
  const top = el.scrollTop + TURN_BAR_HEIGHT + 1
  let index = 0
  turnAnchors().forEach((anchor, i) => { if (anchor.offsetTop <= top) index = i })
  currentTurn.value = index
}
watch(() => turns.value.length, async () => {
  await nextTick()
  updateCurrentTurn()
})
const currentTurnText = computed(() => turns.value[currentTurn.value]?.turn.user?.text || 'Início da sessão')
function goToTurn(index: number) {
  const anchor = turnAnchors()[index]
  if (!anchor) return
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  anchor.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
  anchor.focus({ preventScroll: true })
  currentTurn.value = index
}

// "[" and "]" step through the turns like the bar's buttons, but only while this
// conversation is on screen; the shared guard keeps them out of dialogs, menus and text fields.
function onTurnKey(event: KeyboardEvent) {
  if (!isBareShortcut(event, '[') && !isBareShortcut(event, ']')) return
  if (!props.visible || turns.value.length < 2) return
  const index = currentTurn.value + (event.key === ']' ? 1 : -1)
  if (index < 0 || index >= turns.value.length) return
  event.preventDefault()
  goToTurn(index)
}
onMounted(() => document.addEventListener('keydown', onTurnKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onTurnKey))
watch(
  () => [conv.value?.seq, conv.value?.items.length, conv.value?.prompts.length],
  async ([, items, prompts], [, itemsBefore, promptsBefore]) => {
    const own = (items ?? 0) > (itemsBefore ?? 0)
      && Date.now() - ownSendAt < OWN_SEND_WINDOW_MS
      && conv.value?.items[conv.value.items.length - 1]?.type === 'user'
    if (own) {
      ownSendAt = 0
      atBottom.value = true
      unseen.value = null
    }
    if (!atBottom.value) {
      if ((prompts ?? 0) > (promptsBefore ?? 0)) unseen.value = 'prompt'
      else if ((items ?? 0) > (itemsBefore ?? 0) && unseen.value === null) unseen.value = 'news'
      return
    }
    await nextTick()
    const el = scroller.value
    if (el) el.scrollTop = el.scrollHeight
  },
)

// Images dropped anywhere on the conversation go to the message field.
const composer = ref<InstanceType<typeof MessageComposer> | null>(null)
function onDrop(event: DragEvent) {
  const files = Array.from(event.dataTransfer?.files ?? [])
  if (!files.length || !composer.value) return
  event.preventDefault()
  void composer.value.addFiles(files)
}
function onDragOver(event: DragEvent) {
  if (event.dataTransfer?.types?.includes('Files')) event.preventDefault()
}

function resolvePrompt(promptId: string) {
  conversations.resolvePrompt(props.id, promptId)
}
</script>

<template>
  <div class="flex min-h-0 grow flex-col" @focusin="markSeenSoon" @dragover="onDragOver" @drop="onDrop">
    <template v-if="conv">
      <!-- Screen readers hear finished replies only, never each streamed character. -->
      <div data-test="conversation-live" aria-live="polite" class="sr-only">{{ announcement }}</div>
      <div class="relative flex min-h-0 grow flex-col">
      <div ref="scroller" data-test="conversation-scroller" class="relative min-h-0 grow overflow-y-auto" @scroll="onScroll">
        <div
          v-if="turns.length >= 2"
          data-test="turn-bar"
          class="sticky top-0 z-10 border-b border-line bg-panel"
        >
          <div data-test="chat-bar-column" class="mx-auto flex h-11 w-full max-w-(--chat-width) items-center gap-2.5 px-4">
            <span class="cap shrink-0 text-fg-subtle">Turno {{ currentTurn + 1 }} de {{ turns.length }}</span>
            <span class="min-w-0 grow truncate text-[0.8125rem] text-fg">{{ currentTurnText }}</span>
            <button
              type="button"
              aria-label="Turno anterior"
              title="Turno anterior ([)"
              aria-keyshortcuts="["
              class="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-lg border border-line-strong bg-transparent text-fg-muted hover:text-fg focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-default disabled:opacity-40"
              :disabled="currentTurn === 0"
              @click="goToTurn(currentTurn - 1)"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m18 15-6-6-6 6" /></svg>
            </button>
            <button
              type="button"
              aria-label="Próximo turno"
              title="Próximo turno (])"
              aria-keyshortcuts="]"
              class="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-lg border border-line-strong bg-transparent text-fg-muted hover:text-fg focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-default disabled:opacity-40"
              :disabled="currentTurn >= turns.length - 1"
              @click="goToTurn(currentTurn + 1)"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
            </button>
          </div>
        </div>
        <div data-test="chat-body-column" class="mx-auto flex w-full max-w-(--chat-width) flex-col gap-[18px] px-4 pt-5 pb-6">
          <p
            v-if="conv.historyTruncated"
            data-test="history-truncated"
            class="m-0 rounded-md border border-line bg-card px-3 py-1.5 text-center text-xs text-fg-muted"
          >Mostrando as mensagens mais recentes.</p>
          <p v-if="rows.length === 0" class="m-0 py-8 text-center text-sm text-fg-muted">
            Nenhuma mensagem ainda. Escreva abaixo para começar.
          </p>
          <template v-for="({ turn, done, last, waiting, summary, failed }, index) in turns" :key="turn.user?.id ?? 'before-first-message'">
            <div v-if="index > 0" data-test="turn-separator" data-turn-anchor tabindex="-1" class="mt-1.5 flex scroll-mt-11 focus-visible:outline-2 focus-visible:outline-primary items-center gap-2.5">
              <span class="cap text-fg-subtle">Turno {{ turn.number }}</span>
              <span aria-hidden="true" class="h-px grow bg-line" />
            </div>
            <div
              data-test="turn"
              :data-turn-anchor="index === 0 ? '' : undefined"
              :tabindex="index === 0 ? -1 : undefined"
              class="flex scroll-mt-11 flex-col gap-3.5 focus-visible:outline-2 focus-visible:outline-primary"
            >
              <UserMessage v-if="turn.user" :item="turn.user" />
              <div v-if="turn.entries.length" class="relative flex flex-col gap-[18px]">
                <div aria-hidden="true" class="absolute top-1.5 bottom-1.5 left-[13px] w-px bg-line" />
                <div v-for="entry in turn.entries" :key="entry.kind === 'group' ? `group-${entry.id}` : entry.item.id" class="relative flex items-start gap-3">
                  <template v-if="entry.kind === 'group'">
                    <RailNode :kind="groupNodeKind(entry.items, sessionActive, waitingIds)" align="group" />
                    <WorkBlock
                      class="min-w-0 grow"
                      :items="entry.items"
                      :open="blockOpen(entry, done)"
                      :session-active="sessionActive"
                      :children-of="tree.childrenOf"
                      :task-list="taskList"
                      @toggle="groupChoice.set(entry.id, !blockOpen(entry, done))"
                    />
                  </template>
                  <template v-else>
                    <RailNode :kind="nodeKind(entry.item, sessionActive, waitingIds)" :align="railAlign(entry.item)" />
                    <div class="flex min-w-0 grow flex-col">
                      <ConversationBlock
                        :item="entry.item"
                        :session-active="sessionActive"
                        :children-of="tree.childrenOf"
                        :task-list="taskList"
                      />
                    </div>
                  </template>
                </div>
              </div>
              <div v-if="done" data-test="turn-end" class="flex flex-wrap items-center gap-y-0.5 text-xs text-fg-subtle">
                <button
                  v-if="waiting"
                  type="button"
                  data-test="turn-waiting"
                  class="flex min-h-6 cursor-pointer items-center gap-2 rounded border-none bg-transparent p-0 text-left text-xs text-fg-muted hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                  title="Ir ao cartão"
                  @click="goToSubagent(backgroundRunning[0]!.id)"
                >
                  <span data-test="turn-waiting-dot" class="size-2 shrink-0 animate-pulse rounded-full bg-secondary motion-reduce:animate-none" aria-hidden="true" />
                  {{ waitingLabel }}
                </button>
                <template v-else>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" class="mr-1.5 shrink-0" :class="last ? 'text-primary' : 'text-fg-subtle'" aria-hidden="true"><path d="M20 6 9 17l-5-5" /></svg>
                  <span data-test="turn-end-label" class="font-medium" :class="last ? 'text-primary-soft' : 'text-fg-subtle'">Concluído</span>
                  <span v-if="summary" data-test="turn-end-summary" class="text-fg-subtle">{{ ` · ${summary}` }}</span>
                  <template v-if="failed">
                    <span class="text-fg-subtle">{{ ' · ' }}</span>
                    <span data-test="turn-end-error" class="text-diff-del-fg">terminou com erro</span>
                  </template>
                </template>
              </div>
            </div>
          </template>
          <template v-for="prompt in conv.prompts" :key="prompt.prompt_id">
            <QuestionCard
              data-prompt-card
              tabindex="-1"
              class="focus-visible:outline-2 focus-visible:outline-primary"
              v-if="prompt.kind === 'question'"
              :session-id="conv.sessionId"
              :prompt="prompt"
              @resolved="resolvePrompt(prompt.prompt_id)"
            />
            <PlanCard
              data-prompt-card
              tabindex="-1"
              class="focus-visible:outline-2 focus-visible:outline-primary"
              v-else-if="prompt.kind === 'plan'"
              :session-id="conv.sessionId"
              :prompt="prompt"
              @resolved="resolvePrompt(prompt.prompt_id)"
            />
            <PermissionCard
              data-prompt-card
              tabindex="-1"
              class="focus-visible:outline-2 focus-visible:outline-primary"
              v-else
              :session-id="conv.sessionId"
              :prompt="prompt"
              @resolved="resolvePrompt(prompt.prompt_id)"
            />
          </template>
        </div>
      </div>
      <Transition enter-active-class="transition-opacity duration-150" enter-from-class="opacity-0" leave-active-class="transition-opacity duration-150" leave-to-class="opacity-0">
        <button
          v-if="unseen"
          type="button"
          data-test="jump-to-end"
          class="absolute bottom-3 left-1/2 z-20 flex min-h-8 -translate-x-1/2 cursor-pointer items-center gap-1.5 rounded-full border px-3.5 text-[0.8125rem] font-medium shadow-lg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          :class="jumpLabel === 'Pedido abaixo' ? 'border-secondary bg-secondary text-secondary-fg hover:bg-secondary-soft' : 'border-line-strong bg-card text-fg hover:bg-elevated'"
          @click="jumpToEnd"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14" /><path d="m19 12-7 7-7-7" /></svg>
          {{ jumpLabel }}
        </button>
      </Transition>
      </div>

      <div class="border-t border-line">
        <div data-test="chat-composer-column" class="mx-auto flex w-full max-w-(--chat-width) flex-col gap-2.5 px-4 pt-3 pb-3.5">
          <p
            v-if="conv.state === 'error'"
            data-test="session-error"
            role="alert"
            class="m-0 rounded-md border border-diff-del-fg/40 bg-diff-del-bg px-3 py-2 text-sm text-diff-del-fg"
          >
            {{ conv.error || 'A sessão parou com erro.' }} Você pode enviar de novo.
          </p>
          <p v-if="loadError" role="alert" class="m-0 rounded-md border border-diff-del-fg/40 bg-diff-del-bg px-3 py-2 text-sm text-diff-del-fg">{{ loadError }}</p>
          <SubagentStrip :session-id="conv.sessionId" :entries="subagentEntries" @select="goToSubagent" />
          <MessageComposer ref="composer" :key="conv.sessionId" :session-id="conv.sessionId" :state="conv.state" :blocked-reason="unavailableReason" @sending="ownSendAt = Date.now()">
            <template #controls><SessionControls :session-id="conv.sessionId" /></template>
          </MessageComposer>
        </div>
      </div>
    </template>
    <div v-else class="flex flex-col items-start gap-3 px-6 py-8">
      <p v-if="loadError" role="alert" class="m-0 rounded-md border border-diff-del-fg/40 bg-diff-del-bg px-3 py-2 text-diff-del-fg">{{ loadError }}</p>
      <div v-if="loadError" class="flex flex-wrap gap-2">
        <button
          type="button"
          data-test="retry-load"
          :aria-disabled="reloading"
          :aria-busy="reloading"
          class="min-h-9 cursor-pointer rounded-md border border-line-strong bg-elevated px-3 text-sm text-fg hover:bg-line-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary aria-disabled:cursor-default aria-disabled:opacity-60 aria-disabled:hover:bg-elevated"
          @click="!reloading && reload()"
        >
          Tentar de novo
        </button>
      </div>
      <p v-else class="text-fg-muted">Carregando…</p>
    </div>
  </div>
</template>
