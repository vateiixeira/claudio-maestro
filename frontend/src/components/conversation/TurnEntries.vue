<script setup lang="ts">
import RailNode from './RailNode.vue'
import ConversationBlock from './ConversationBlock.vue'
import WorkBlock from './WorkBlock.vue'
import { railAlign } from '../../conversation/railAlign'
import { entryKey } from '../../conversation/liveItems'
import { nodeKind, type TurnEntry } from '../../conversation/turns'
import { groupNodeKind } from '../../conversation/work'
import type { ConversationItem, ToolItem } from '../../types/conversation'
import type { TaskEntry } from '../../conversation/tasks'

/** The rail of one turn: its text, thinking and tool rows, with the work blocks folded. */
defineProps<{
  entries: TurnEntry[]
  sessionActive: boolean
  waitingIds: ReadonlySet<string>
  childrenOf: (toolUseId: string) => ConversationItem[]
  originOf?: (item: ToolItem) => string | undefined
  taskList: { tasks: TaskEntry[]; lastItemId: string | null } | null
  /** Whether a row arrived live (it enters with a motion). */
  isLive: (key: string) => boolean
  /** Open or closed state of a work block; the owner decides it. */
  isOpen: (entry: { id: string; items: ToolItem[] }) => boolean
}>()
defineEmits<{ toggle: [entry: { id: string; items: ToolItem[] }]; reveal: [] }>()
</script>

<template>
  <div class="relative flex flex-col gap-[18px]">
    <div aria-hidden="true" class="absolute top-1.5 bottom-1.5 left-[13px] w-px bg-line" />
    <div v-for="entry in entries" :key="entryKey(entry)" data-test="turn-entry" class="relative flex items-start gap-3" :class="{ 'animate-enter': isLive(entryKey(entry)) }">
      <template v-if="entry.kind === 'group'">
        <RailNode :kind="groupNodeKind(entry.items, sessionActive, waitingIds)" align="group" :live="isLive(entryKey(entry))" />
        <WorkBlock
          class="min-w-0 grow"
          :items="entry.items"
          :open="isOpen(entry)"
          :session-active="sessionActive"
          :waiting-ids="waitingIds"
          :children-of="childrenOf"
          :origin-of="originOf"
          :task-list="taskList"
          @toggle="$emit('toggle', entry)"
        />
      </template>
      <template v-else>
        <RailNode :kind="nodeKind(entry.item, sessionActive, waitingIds)" :align="railAlign(entry.item)" :live="isLive(entryKey(entry))" />
        <div class="flex min-w-0 grow flex-col">
          <ConversationBlock
            :item="entry.item"
            :session-active="sessionActive"
            :children-of="childrenOf"
            :task-list="taskList"
            @reveal="$emit('reveal')"
          />
        </div>
      </template>
    </div>
  </div>
</template>
