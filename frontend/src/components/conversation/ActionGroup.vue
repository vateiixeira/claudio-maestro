<script setup lang="ts">
import { computed, reactive } from 'vue'
import type { TaskEntry } from '../../conversation/tasks'
import { actionRow, groupChips } from '../../conversation/turns'
import type { ConversationItem, ToolItem } from '../../types/conversation'
import ConversationBlock from './ConversationBlock.vue'
import IconChevron from '../icons/IconChevron.vue'

// Two or more consecutive light actions of a turn, shown as one collapsible block.
const props = withDefaults(
  defineProps<{
    items: ToolItem[]
    open: boolean
    sessionActive?: boolean
    childrenOf?: (toolUseId: string) => ConversationItem[]
    taskList?: { tasks: TaskEntry[]; lastItemId: string | null } | null
  }>(),
  { sessionActive: false, childrenOf: () => [], taskList: null },
)
const emit = defineEmits<{ toggle: [] }>()

const chips = computed(() => groupChips(props.items))
const rows = computed(() => props.items.map((item) => ({ item, ...actionRow(item, props.sessionActive) })))
const expanded = reactive(new Set<string>())
function toggleRow(id: string) {
  if (expanded.has(id)) expanded.delete(id)
  else expanded.add(id)
}
</script>

<template>
  <div data-test="action-group" class="overflow-hidden rounded-lg border border-line bg-panel">
    <button
      type="button"
      data-test="action-group-toggle"
      class="flex min-h-11 w-full cursor-pointer items-center gap-2.5 border-none bg-transparent px-3 text-left text-fg"
      :aria-expanded="open"
      @click="emit('toggle')"
    >
      <span class="cap shrink-0 text-fg-subtle">{{ items.length }} ações</span>
      <span class="flex min-w-0 grow flex-wrap gap-1.5">
        <span
          v-for="chip in chips"
          :key="chip"
          data-test="group-chip"
          class="rounded border border-line px-1.5 py-px font-mono text-[11px] text-fg-muted"
        >{{ chip }}</span>
      </span>
      <span class="flex shrink-0 items-center gap-1 text-xs text-fg-subtle">{{ open ? 'Recolher' : 'Ver' }}<IconChevron :open="open" :size="12" /></span>
    </button>
    <div v-if="open" class="flex flex-col border-t border-line">
      <template v-for="(row, index) in rows" :key="row.item.id">
        <button
          type="button"
          data-test="action-row"
          class="flex h-[34px] w-full cursor-pointer items-center gap-2.5 border-x-0 border-b-0 bg-transparent px-3 text-left text-fg"
          :class="index > 0 ? 'border-t border-line' : 'border-t-0'"
          :aria-expanded="expanded.has(row.item.id)"
          @click="toggleRow(row.item.id)"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 text-fg-subtle" aria-hidden="true">
            <template v-if="row.kind === 'read'"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6" /></template>
            <template v-else-if="row.kind === 'search'"><circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.5" y2="16.5" /></template>
            <template v-else-if="row.kind === 'bash'"><path d="m4 17 6-6-6-6" /><line x1="12" y1="19" x2="20" y2="19" /></template>
            <path v-else d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z" />
          </svg>
          <span class="cap w-20 shrink-0 text-fg-subtle">{{ row.label }}</span>
          <span class="min-w-0 grow truncate font-mono text-xs text-fg">{{ row.target }}</span>
          <span
            v-if="row.meta"
            class="max-w-[45%] shrink-0 truncate font-mono text-[11px]"
            :class="row.meta === 'rodando…' ? 'animate-pulse text-primary-soft' : 'text-fg-subtle'"
          >{{ row.meta }}</span>
        </button>
        <div v-if="expanded.has(row.item.id)" data-test="action-row-card" class="border-t border-line p-2">
          <ConversationBlock :item="row.item" :session-active="sessionActive" :children-of="childrenOf" :task-list="taskList" />
        </div>
      </template>
    </div>
  </div>
</template>
