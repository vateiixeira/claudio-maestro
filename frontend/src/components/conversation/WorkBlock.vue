<script setup lang="ts">
import { computed, inject, nextTick, reactive, ref, watch } from 'vue'
import type { TaskEntry } from '../../conversation/tasks'
import { formatRunningTime } from '../../format'
import { SUBAGENT_FOCUS_KEY } from '../../conversation/subagents'
import { resultText } from '../../conversation/tool'
import { workCaption, workFailure, workRetries, workRow, workStatus, type WorkKind } from '../../conversation/work'
import { workFolders, workGroups, workSpan } from '../../conversation/workGroups'
import { useSecondClock } from '../../secondClock'
import type { ConversationItem, ToolItem } from '../../types/conversation'
import ConversationBlock from './ConversationBlock.vue'
import ToolImageStrip from './ToolImageStrip.vue'
import Collapse from '../Collapse.vue'
import IconChevron from '../icons/IconChevron.vue'
import IconWorkKind from '../icons/IconWorkKind.vue'
import WorkArtifacts from './WorkArtifacts.vue'
import WorkError from './WorkError.vue'
import WorkHeader from './WorkHeader.vue'

// Everything Claude did between two statements, in one collapsible box: the actions in groups of the same
// kind, one row per action.
const props = withDefaults(
  defineProps<{
    items: ToolItem[]
    open: boolean
    sessionActive?: boolean
    /** `tool_use_id`s of the requests the user has yet to answer: those actions wait for the user. */
    waitingIds?: ReadonlySet<string>
    childrenOf?: (toolUseId: string) => ConversationItem[]
    /** The subagent a file write came from (a subagent's write shown as a row of its own); undefined for an action of the main agent. */
    originOf?: (item: ToolItem) => string | undefined
    taskList?: { tasks: TaskEntry[]; lastItemId: string | null } | null
    /** When the block ended (Unix seconds): the time of whatever came after it in the turn. */
    endAt?: number | null
  }>(),
  { sessionActive: false, waitingIds: undefined, childrenOf: () => [], originOf: undefined, taskList: null, endAt: null },
)
const emit = defineEmits<{ toggle: [] }>()

const count = computed(() => (props.items.length === 1 ? '1 ação' : `${props.items.length} ações`))
const summary = computed(() => workCaption(props.items, props.sessionActive, props.waitingIds))
// The caption enters when its text changes, not when the group first appears.
const summaryChanged = ref(false)
watch(summary, () => { summaryChanged.value = true })
const running = computed(() => props.items.some((item) => workStatus(item, props.sessionActive, props.waitingIds) === 'running'))
const rows = computed(() => props.items.map((item) => ({ item, ...workRow(item, props.sessionActive, props.waitingIds, props.originOf?.(item)) })))
const groups = computed(() => workGroups(rows.value))

const failure = computed(() => workFailure(props.items, props.sessionActive, props.waitingIds))
const retries = computed(() => workRetries(props.items, props.sessionActive, props.waitingIds))
const retryIds = computed(() => new Set(retries.value.values()))
const statusById = computed(() => new Map(rows.value.map((row) => [row.item.id, row.status])))
// A failed action whose next attempt passed: the row says so.
const retryPassed = (id: string) => {
  const next = retries.value.get(id)
  return next != null && statusById.value.get(next) === 'ok'
}

const folders = computed(() => workFolders(props.items))

// The time of a running action ("12 s") and the block's own duration. One clock for the whole app, on only
// while an action with a known start runs in the block, open or closed.
const ticking = computed(() => running.value && (props.items[0]?.at != null || rows.value.some((row) => row.status === 'running' && row.at != null)))
const now = useSecondClock(ticking)
const elapsedOf = (row: { status: string; at?: number }) =>
  row.status === 'running' && row.at != null ? formatRunningTime(now.value / 1000 - row.at) : undefined
const spanText = computed(() => {
  const seconds = workSpan(props.items, props.endAt, now.value / 1000, running.value)
  return seconds == null ? '' : formatRunningTime(Math.round(seconds))
})

// A row is closed unless the user opened it; one that failed opens by itself, until the user chooses otherwise.
const choice = reactive(new Map<string, boolean>())
const isOpen = (id: string, failed: boolean) => choice.get(id) ?? failed
function toggleRow(id: string, failed: boolean) {
  choice.set(id, !isOpen(id, failed))
}

// The subagent strip or the turn footer asks to reach an action in the block (or one inside a subagent
// of the block): open the block and the row.
const focus = inject(SUBAGENT_FOCUS_KEY, ref(null))
watch(focus, (target) => {
  if (!target) return
  const hit = props.items.find((item) => target.path.includes(item.id))
  if (!hit) return
  choice.set(hit.id, true)
  if (!props.open) emit('toggle')
})

// A chip of what the closed block produced: open the block on the action behind it. The chip goes away
// with the closed block, so the focus follows to the button of the row that opens.
const root = ref<HTMLElement | null>(null)
const focusRowOf = ref<string | null>(null)
async function openFrom(id: string) {
  choice.set(id, true)
  focusRowOf.value = id
  if (!props.open) emit('toggle')
  // The parent answers in the same flush; if the block is still closed after it, the focus has nowhere to go
  // and must not jump to the row when the block opens for another reason.
  await nextTick()
  if (!props.open) focusRowOf.value = null
}
watch([() => props.open, focusRowOf], async ([open, id]) => {
  if (!open || !id) return
  focusRowOf.value = null
  await nextTick()
  const rowsInBlock = Array.from(root.value?.querySelectorAll<HTMLElement>('[data-row-id]') ?? [])
  rowsInBlock.find((row) => row.dataset.rowId === id)?.querySelector<HTMLElement>('[data-test="work-header"]')?.focus()
})

type Family = 'command' | 'file' | 'agent'
const FAMILY: Record<WorkKind, Family> = { bash: 'command', tool: 'command', read: 'file', search: 'file', edit: 'file', agent: 'agent' }
// Whole class names, so Tailwind finds them.
const GROUP_TONE: Record<Family, string> = {
  command: 'text-type-command bg-[color-mix(in_oklab,var(--color-type-command)_9%,transparent)]',
  file: 'text-type-file bg-[color-mix(in_oklab,var(--color-type-file)_9%,transparent)]',
  agent: 'text-type-agent bg-[color-mix(in_oklab,var(--color-type-agent)_9%,transparent)]',
}
const FAILED_FILL = 'bg-[color-mix(in_oklab,var(--color-diff-del-fg)_8%,transparent)]'
const errorText = (item: ToolItem) => resultText(item.result?.content).trim()
</script>

<template>
  <div ref="root" data-test="work-block" class="min-w-0">
    <div class="flex flex-col gap-2.5">
      <button
        type="button"
        data-test="work-block-toggle"
        class="flex min-h-9 w-full max-w-full cursor-pointer items-center gap-2.5 rounded border-none bg-transparent px-0 py-1 text-left text-sm hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
        :aria-expanded="open"
        :title="summary"
        :aria-label="`${open ? 'Recolher' : 'Ver'} ${count}: ${summary}${failure ? ` · ${failure}` : ''}`"
        @click="emit('toggle')"
      >
        <span data-test="work-count" class="sr-only">{{ count }}</span>
        <span
          :key="summary"
          data-test="work-summary"
          class="min-w-0 truncate"
          :class="[
            running ? 'text-secondary-soft' : open ? 'text-fg' : 'text-fg-muted',
            open ? 'font-medium' : '',
            summaryChanged ? 'animate-enter [animation-duration:var(--motion-state)]' : '',
          ]"
        >{{ summary }}</span>
        <span v-if="folders > 1" data-test="work-folders" class="shrink-0 font-mono text-xs text-fg-muted">em {{ folders }} pastas</span>
        <span v-if="failure" data-test="work-failed" class="inline-flex h-[1.375rem] shrink-0 items-center gap-1.5 rounded-full bg-diff-del-bg px-2.5 text-xs font-medium text-diff-del-fg">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>{{ failure }}
        </span>
        <span class="grow" />
        <span v-if="spanText" data-test="work-span" class="shrink-0 font-mono text-xs tabular-nums" :class="running ? 'text-secondary-soft' : 'text-fg-muted'">{{ spanText }}</span>
        <IconChevron :open="open" :size="12" class="shrink-0 text-fg-subtle duration-(--motion-enter) ease-(--ease-maestro)" />
      </button>
      <!-- The images of the block's own actions (not a subagent's), in view with the block closed. -->
      <ToolImageStrip :items="items" :session-active="sessionActive" />
      <WorkArtifacts v-if="!open" :items="items" :session-active="sessionActive" @open="openFrom" />
    </div>
    <Collapse :open="open">
      <div class="mt-2.5 flex flex-col overflow-hidden rounded-xl border border-line bg-panel">
        <div v-for="(group, groupIndex) in groups" :key="group.key" data-test="work-group" :data-kind="group.kind" :class="groupIndex > 0 ? 'border-t border-line' : ''">
          <div data-test="work-group-head" class="flex min-h-[2.125rem] items-center gap-2.5 px-3.5" :class="GROUP_TONE[FAMILY[group.kind]]">
            <IconWorkKind :kind="group.kind" :size="13" />
            <span data-test="work-group-label" class="cap">{{ group.label }}</span>
            <span v-if="group.where" data-test="work-group-where" class="min-w-0 truncate font-mono text-xs text-fg-muted" :title="group.where">{{ group.where }}</span>
            <span class="grow" />
            <span data-test="work-group-count" class="shrink-0 font-mono text-xs text-fg-muted">{{ group.rows.length }}</span>
          </div>
          <div
            v-for="row in group.rows"
            :key="row.item.id"
            data-test="work-row"
            :data-row-id="row.item.id"
            class="border-t border-line"
            :class="row.status === 'error' ? FAILED_FILL : ''"
          >
            <WorkHeader
              as="button"
              grouped
              :kind="row.kind"
              :label="row.label"
              :tag="row.tag"
              :model="row.model"
              :desc="row.desc"
              :mono="row.mono"
              :status="row.status"
              :meta="row.meta"
              :elapsed="elapsedOf(row)"
              :command="isOpen(row.item.id, row.status === 'error') ? undefined : row.command"
              :open="isOpen(row.item.id, row.status === 'error')"
              :aria-expanded="isOpen(row.item.id, row.status === 'error')"
              @click="toggleRow(row.item.id, row.status === 'error')"
            >
              <template v-if="row.diff || retryIds.has(row.item.id)" #trail>
                <template v-if="row.diff">
                  <span v-if="row.diff.added" class="shrink-0 font-mono text-xs text-diff-add-fg">+{{ row.diff.added }}</span>
                  <span v-if="row.diff.removed" class="shrink-0 font-mono text-xs text-diff-del-fg">−{{ row.diff.removed }}</span>
                </template>
                <span v-if="retryIds.has(row.item.id)" data-test="work-retry" class="cap shrink-0 text-fg-muted">Nova tentativa</span>
              </template>
            </WorkHeader>
            <Collapse :open="isOpen(row.item.id, row.status === 'error')">
              <div
                data-test="work-row-body"
                :class="row.status === 'error' ? 'mt-1 mr-3.5 mb-3.5 ml-10 overflow-hidden rounded-lg border border-line bg-surface' : 'border-t border-line bg-surface'"
              >
                <WorkError v-if="row.status === 'error' && errorText(row.item)" :text="errorText(row.item)" />
                <ConversationBlock headless :item="row.item" :session-active="sessionActive" :children-of="childrenOf" :task-list="taskList" />
                <div v-if="row.status === 'error' && retryPassed(row.item.id)" class="flex items-center gap-2 border-t border-line px-3 py-2 text-[0.78rem] text-fg-muted">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0" aria-hidden="true"><path d="M12 5v14M6 13l6 6 6-6" /></svg>
                  <span data-test="work-retry-note">A tentativa seguinte passou.</span>
                </div>
              </div>
            </Collapse>
          </div>
        </div>
      </div>
    </Collapse>
  </div>
</template>
