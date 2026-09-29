<script setup lang="ts">
import type { ConversationItem } from '../../types/conversation'
import BashTool from './BashTool.vue'
import EditTool from './EditTool.vue'
import GenericTool from './GenericTool.vue'
import NoticeBlock from './NoticeBlock.vue'
import ReadTool from './ReadTool.vue'
import TextBlock from './TextBlock.vue'
import ThinkingBlock from './ThinkingBlock.vue'
import UserMessage from './UserMessage.vue'

withDefaults(defineProps<{ item: ConversationItem; sessionActive?: boolean }>(), { sessionActive: false })

const EDIT_TOOLS = new Set(['Edit', 'Write', 'MultiEdit'])
</script>

<template>
  <UserMessage v-if="item.type === 'user'" :item="item" />
  <TextBlock v-else-if="item.type === 'text'" :item="item" />
  <ThinkingBlock v-else-if="item.type === 'thinking'" :item="item" />
  <NoticeBlock v-else-if="item.type === 'notice'" :item="item" />
  <template v-else-if="item.type === 'tool'">
    <ReadTool v-if="item.name === 'Read'" :item="item" :session-active="sessionActive" />
    <EditTool v-else-if="EDIT_TOOLS.has(item.name)" :item="item" :session-active="sessionActive" />
    <BashTool v-else-if="item.name === 'Bash'" :item="item" :session-active="sessionActive" />
    <GenericTool v-else :item="item" :session-active="sessionActive" />
  </template>
</template>
