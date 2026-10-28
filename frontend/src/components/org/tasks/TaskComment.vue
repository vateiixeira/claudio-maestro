<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import AgentStateIcon from '../AgentStateIcon.vue'
import TaskMarkdown from './TaskMarkdown.vue'
import { agentState } from '../../../org'
import { formatActivity } from '../../../format'
import { useOrgStore } from '../../../stores/org'
import { useSessionsStore } from '../../../stores/sessions'
import type { Comment } from '../../../types/org'

// One comment of the thread. The person's is a bubble on the right, an agent's is on the left with its name and
// state, and what the app wrote (status changes, notices) is a quiet centered line.
const props = defineProps<{ comment: Comment }>()
const org = useOrgStore()
const sessions = useSessionsStore()

const agent = computed(() => (props.comment.author_agent_id === null ? undefined : org.byId(props.comment.author_agent_id)))
const state = computed(() => (agent.value ? agentState(agent.value, sessions.all) : null))
const when = computed(() => formatActivity(props.comment.created_at))
const iso = computed(() => new Date(props.comment.created_at * 1000).toISOString())
</script>

<template>
  <li
    v-if="comment.author_kind === 'app'"
    data-test="task-comment"
    data-author="app"
    :data-comment-id="comment.id"
    class="max-w-[85%] self-center text-center text-xs text-fg-subtle [overflow-wrap:anywhere]"
  >
    <span>{{ comment.text }}</span>
    <time :datetime="iso" class="ml-2">{{ when }}</time>
  </li>
  <li
    v-else-if="comment.author_kind === 'human'"
    data-test="task-comment"
    data-author="human"
    :data-comment-id="comment.id"
    class="flex max-w-[85%] min-w-0 flex-col gap-1 self-end rounded-lg border border-line-strong bg-card px-3 py-2"
  >
    <TaskMarkdown :text="comment.text" />
    <time :datetime="iso" class="self-end text-[0.6875rem] text-fg-subtle">{{ when }}</time>
  </li>
  <li
    v-else
    data-test="task-comment"
    data-author="agent"
    :data-comment-id="comment.id"
    class="flex max-w-[85%] min-w-0 flex-col gap-1 self-start rounded-lg bg-panel px-3 py-2"
  >
    <div class="flex items-center gap-1.5 text-xs">
      <AgentStateIcon v-if="state" :state="state" :size="12" />
      <RouterLink v-if="agent" data-test="comment-author" :to="`/agentes/${agent.project_id}?agente=${agent.id}`" class="rounded font-semibold text-fg no-underline hover:underline focus-visible:outline-2 focus-visible:outline-primary">{{ agent.name }}</RouterLink>
      <span v-else data-test="comment-author" class="font-semibold text-fg-muted">Agente removido</span>
      <time :datetime="iso" class="text-fg-subtle">{{ when }}</time>
    </div>
    <TaskMarkdown :text="comment.text" />
  </li>
</template>
