<script setup lang="ts">
import { computed, provide, reactive, toRef } from 'vue'
import PromptCards from './PromptCards.vue'
import TurnEntries from './TurnEntries.vue'
import UserMessage from './UserMessage.vue'
import { SESSION_ID_KEY } from '../../stores/changesPanel'
import { useConversationStore } from '../../stores/conversation'
import { useSessionConversation } from '../../conversation/useSessionConversation'
import { buildItemTree } from '../../conversation/subagents'
import { buildTurns } from '../../conversation/turns'
import { waitingIdsOf } from '../../conversation/waiting'
import { hasUnrecoveredFailure } from '../../conversation/work'
import type { ToolItem } from '../../types/conversation'

/**
 * The steps of one run: the turns of another session (messages, actions and pending requests) drawn
 * inside a conversation. No turn bar and no message field: it only shows what the session did.
 * `prompts` false leaves the pending requests out, for a parent that already shows them.
 */
const props = withDefaults(defineProps<{ sessionId: string; prompts?: boolean }>(), { prompts: true })

const conversations = useConversationStore()
const { conv, loading, error, reload } = useSessionConversation(toRef(props, 'sessionId'))

// Images and diffs of the steps belong to the run's session, not to the conversation around them.
provide(SESSION_ID_KEY, computed(() => props.sessionId))

const tree = computed(() => buildItemTree(conv.value?.items ?? []))
const turns = computed(() => buildTurns(tree.value.top))
const sessionActive = computed(() => conv.value?.state === 'running' || conv.value?.state === 'awaiting_decision')
const taskList = computed(() => conversations.taskList(props.sessionId))
const waitingIds = computed(() => waitingIdsOf(conv.value?.items ?? [], conv.value?.prompts ?? []))

// Open/closed chosen by the user per work block (by id); unset folds the block, except a failure nobody tried again.
const groupChoice = reactive(new Map<string, boolean>())
function blockOpen(entry: { id: string; items: ToolItem[] }): boolean {
  return groupChoice.get(entry.id)
    ?? hasUnrecoveredFailure(entry.items, sessionActive.value, waitingIds.value)
}
function toggleBlock(entry: { id: string; items: ToolItem[] }) {
  groupChoice.set(entry.id, !blockOpen(entry))
}
const notLive = () => false
</script>

<template>
  <div data-test="run-steps" class="flex flex-col gap-3.5">
    <template v-if="conv">
      <div v-for="turn in turns" :key="turn.user?.id ?? 'before-first-message'" data-test="run-turn" class="flex flex-col gap-3.5">
        <UserMessage v-if="turn.user" :item="turn.user" />
        <TurnEntries
          v-if="turn.entries.length"
          :entries="turn.entries"
          :session-active="sessionActive"
          :waiting-ids="waitingIds"
          :children-of="tree.childrenOf"
          :origin-of="tree.originOf"
          :task-list="taskList"
          :is-live="notLive"
          :is-open="blockOpen"
          @toggle="toggleBlock"
        />
      </div>
      <PromptCards v-if="prompts" :session-id="conv.sessionId" :prompts="conv.prompts" :is-live="notLive" @resolved="conversations.resolvePrompt(conv.sessionId, $event)" />
    </template>
    <p v-if="error" role="alert" class="m-0 rounded-md border border-diff-del-fg/40 bg-diff-del-bg px-3 py-2 text-sm text-diff-del-fg">{{ error }}</p>
    <div v-if="error" class="flex flex-wrap gap-2">
      <button
        type="button"
        data-test="retry-load"
        :aria-disabled="loading"
        :aria-busy="loading"
        class="min-h-9 cursor-pointer rounded-md border border-line-strong bg-elevated px-3 text-sm text-fg hover:bg-line-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary aria-disabled:cursor-default aria-disabled:opacity-60 aria-disabled:hover:bg-elevated"
        @click="!loading && reload()"
      >
        Tentar de novo
      </button>
    </div>
    <p v-else-if="!conv" class="m-0 text-sm text-fg-muted">Carregando…</p>
  </div>
</template>
