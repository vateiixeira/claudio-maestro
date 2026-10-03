<script setup lang="ts">
import { computed, inject, reactive, ref, watch } from 'vue'
import type { TaskEntry } from '../../conversation/tasks'
import { formatRunningTime } from '../../format'
import { SUBAGENT_FOCUS_KEY } from '../../conversation/subagents'
import { workActivity, workRow, workSummary } from '../../conversation/work'
import { useSecondClock } from '../../secondClock'
import type { ConversationItem, ToolItem } from '../../types/conversation'
import ConversationBlock from './ConversationBlock.vue'
import Collapse from '../Collapse.vue'
import IconChevron from '../icons/IconChevron.vue'
import WorkHeader from './WorkHeader.vue'

// Everything Claude did between two statements, in one collapsible box: one row per action.
const props = withDefaults(
  defineProps<{
    items: ToolItem[]
    open: boolean
    sessionActive?: boolean
    /** `tool_use_id`s of the requests the user has yet to answer: those actions wait for the user. */
    waitingIds?: ReadonlySet<string>
    childrenOf?: (toolUseId: string) => ConversationItem[]
    taskList?: { tasks: TaskEntry[]; lastItemId: string | null } | null
  }>(),
  { sessionActive: false, waitingIds: undefined, childrenOf: () => [], taskList: null },
)
const emit = defineEmits<{ toggle: [] }>()

const count = computed(() => (props.items.length === 1 ? '1 ação' : `${props.items.length} ações`))
const summary = computed(() => workSummary(props.items, props.sessionActive, props.waitingIds))
// The summary ("2 comandos ok") enters when its text changes, not when the block first appears.
const summaryChanged = ref(false)
watch(summary, () => { summaryChanged.value = true })
// While the block is closed and something runs, one line says what.
const activity = computed(() => workActivity(props.items, props.sessionActive, props.waitingIds))
const rows = computed(() => props.items.map((item) => ({ item, ...workRow(item, props.sessionActive, props.waitingIds) })))

// The time of a running action ("12 s"). One clock for the whole app, on only while the block is open and
// an action with a known start runs in it.
const ticking = computed(() => props.open && rows.value.some((row) => row.status === 'running' && row.at != null))
const now = useSecondClock(ticking)
const elapsedOf = (row: { status: string; at?: number }) =>
  row.status === 'running' && row.at != null ? formatRunningTime(now.value / 1000 - row.at) : undefined

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
</script>

<template>
  <div data-test="work-block" class="overflow-hidden rounded-lg border border-line bg-panel">
    <button
      type="button"
      data-test="work-block-toggle"
      class="flex min-h-11 w-full cursor-pointer items-center gap-2.5 border-none bg-transparent px-3 text-left text-fg focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary"
      :aria-expanded="open"
      @click="emit('toggle')"
    >
      <span data-test="work-count" class="cap shrink-0 text-fg-subtle">{{ count }}</span>
      <span
        :key="summary"
        data-test="work-summary"
        class="min-w-0 grow truncate text-xs text-fg-subtle"
        :class="summaryChanged ? 'animate-enter [animation-duration:var(--motion-state)]' : ''"
      >{{ summary }}</span>
      <span class="flex shrink-0 items-center gap-1 text-xs text-fg-subtle">{{ open ? 'Recolher' : 'Ver' }}<IconChevron :open="open" :size="12" class="duration-(--motion-enter) ease-(--ease-maestro)" /></span>
    </button>
    <p v-if="!open && activity" data-test="work-activity" class="m-0 truncate px-3 pb-2.5 font-mono text-[0.6875rem] text-secondary-soft">{{ activity }}</p>
    <Collapse :open="open">
      <div class="flex flex-col border-t border-line">
        <div v-for="(row, index) in rows" :key="row.item.id" data-test="work-row" :class="index > 0 ? 'border-t border-line' : ''">
          <WorkHeader
            as="button"
            :kind="row.kind"
            :label="row.label"
            :tag="row.tag"
            :desc="row.desc"
            :mono="row.mono"
            :status="row.status"
            :meta="row.meta"
            :elapsed="elapsedOf(row)"
            :open="isOpen(row.item.id, row.status === 'error')"
            :aria-expanded="isOpen(row.item.id, row.status === 'error')"
            @click="toggleRow(row.item.id, row.status === 'error')"
          >
            <template v-if="row.command && !isOpen(row.item.id, row.status === 'error')" #desc>
              <span class="block truncate">{{ row.desc }}</span>
              <span data-test="work-command" class="block truncate font-mono text-xs text-fg-muted">{{ row.command }}</span>
            </template>
            <template v-if="row.diff" #trail>
              <span class="shrink-0 font-mono text-xs text-diff-add-fg">+{{ row.diff.added }}</span>
              <span class="shrink-0 font-mono text-xs text-diff-del-fg">−{{ row.diff.removed }}</span>
            </template>
          </WorkHeader>
          <Collapse :open="isOpen(row.item.id, row.status === 'error')">
            <div data-test="work-row-body" class="border-t border-line bg-surface">
              <ConversationBlock headless :item="row.item" :session-active="sessionActive" :children-of="childrenOf" :task-list="taskList" />
            </div>
          </Collapse>
        </div>
      </div>
    </Collapse>
  </div>
</template>
