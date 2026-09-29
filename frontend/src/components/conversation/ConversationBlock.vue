<script setup lang="ts">
import { computed } from 'vue'
import type { TaskEntry } from '../../conversation/tasks'
import { TASK_TOOLS } from '../../conversation/tasks'
import type { ConversationItem } from '../../types/conversation'
import AgentTool from './AgentTool.vue'
import BashTool from './BashTool.vue'
import EditTool from './EditTool.vue'
import GenericTool from './GenericTool.vue'
import NoticeBlock from './NoticeBlock.vue'
import ReadTool from './ReadTool.vue'
import SearchTool from './SearchTool.vue'
import TaskTool from './TaskTool.vue'
import TextBlock from './TextBlock.vue'
import ThinkingBlock from './ThinkingBlock.vue'
import UserMessage from './UserMessage.vue'

const props = withDefaults(
  defineProps<{
    item: ConversationItem
    sessionActive?: boolean
    /** Items whose `parent_tool_use_id` is the given tool call. */
    childrenOf?: (toolUseId: string) => ConversationItem[]
    /** A task list to show in this block (overrides `taskList`). */
    tasks?: TaskEntry[] | null
    /** The session's task list; shown in the block that last changed it, at any depth. */
    taskList?: { tasks: TaskEntry[]; lastItemId: string | null } | null
  }>(),
  { sessionActive: false, childrenOf: () => [], tasks: null, taskList: null },
)

const EDIT_TOOLS = new Set(['Edit', 'Write', 'MultiEdit'])
const SEARCH_TOOLS = new Set(['Grep', 'Glob', 'WebSearch', 'WebFetch'])
const AGENT_TOOLS = new Set(['Agent', 'Task'])

const shownTasks = computed(() =>
  props.tasks ?? (props.taskList && props.taskList.lastItemId === props.item.id ? props.taskList.tasks : null),
)
const children = computed(() => (props.item.type === 'tool' ? props.childrenOf(props.item.tool_use_id) : []))
</script>

<template>
  <UserMessage v-if="item.type === 'user'" :item="item" />
  <TextBlock v-else-if="item.type === 'text'" :item="item" />
  <ThinkingBlock v-else-if="item.type === 'thinking'" :item="item" />
  <NoticeBlock v-else-if="item.type === 'notice'" :item="item" />
  <template v-else-if="item.type === 'tool'">
  <AgentTool v-if="AGENT_TOOLS.has(item.name)" :item="item" :child-count="children.length" :session-active="sessionActive">
    <ConversationBlock
      v-for="child in children"
      :key="child.id"
      :item="child"
      :session-active="sessionActive"
      :children-of="childrenOf"
      :task-list="taskList"
    />
  </AgentTool>
  <div v-else class="flex min-w-0 flex-col gap-2">
    <ReadTool v-if="item.name === 'Read'" :item="item" :session-active="sessionActive" />
    <EditTool v-else-if="EDIT_TOOLS.has(item.name)" :item="item" :session-active="sessionActive" />
    <BashTool v-else-if="item.name === 'Bash'" :item="item" :session-active="sessionActive" />
    <SearchTool v-else-if="SEARCH_TOOLS.has(item.name)" :item="item" :session-active="sessionActive" />
    <TaskTool v-else-if="TASK_TOOLS.has(item.name)" :item="item" :tasks="shownTasks" />
    <p v-else-if="item.name === 'ToolSearch'" data-test="tool-search" class="m-0 font-mono text-xs text-fg-muted">{{ item.result ? 'Ferramentas carregadas' : 'Carregando ferramentas…' }}</p>
    <GenericTool v-else :item="item" :session-active="sessionActive" />
    <div v-if="children.length" data-test="tool-children" class="flex flex-col gap-2 border-l border-line pl-4">
      <ConversationBlock
        v-for="child in children"
        :key="child.id"
        :item="child"
        :session-active="sessionActive"
        :children-of="childrenOf"
      :task-list="taskList"
      />
    </div>
  </div>
  </template>
</template>
