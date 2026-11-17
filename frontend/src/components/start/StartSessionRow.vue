<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import ClosureBadge from '../ClosureBadge.vue'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import ProjectTag from '../conversation/ProjectTag.vue'
import SessionActivity from '../conversation/SessionActivity.vue'
import { needsYou } from '../../conversation/needsYou'
import { formatActivity } from '../../format'
import type { Session } from '../../types/api'

// One conversation in the columns of the start screen: the state, the title and one line under it with what
// stands out (closure or finished plan), the project, and the activity (running) or the short summary (waiting).
// The whole row opens the conversation.
const props = defineProps<{ session: Session }>()

const running = computed(() => props.session.display_state === 'running')
const wantsYou = computed(() => needsYou(props.session))
</script>

<template>
  <RouterLink
    :to="{ name: 'session', params: { id: session.session_id } }"
    class="flex min-w-0 items-start gap-2.5 border-b border-line px-1 py-2.5 text-fg no-underline hover:bg-panel focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
  >
    <DisplayStateIcon class="mt-1.5" :display="session.display_state" :quiet="!wantsYou" :size="13" />
    <span class="flex min-w-0 grow flex-col gap-0.5">
      <span class="truncate text-sm" :class="session.unread ? 'font-medium' : 'font-normal'">{{ session.title || 'Conversa sem título' }}</span>
      <span class="flex min-w-0 items-center gap-2 text-xs text-fg-muted">
        <ClosureBadge :session="session" />
        <span
          v-if="session.plan_done"
          data-test="row-plan-done"
          class="shrink-0 rounded-full border border-primary/40 px-1.5 font-mono text-[0.6875rem] text-primary-soft"
        >Plano concluído</span>
        <ProjectTag class="shrink-0" :project-id="session.project_id" />
        <SessionActivity v-if="running" :session="session" />
        <span v-else-if="session.digest_short" data-test="row-digest" class="min-w-0 truncate">{{ session.digest_short }}</span>
        <template v-if="!running">
          <span class="flex-1" />
          <span data-test="start-row-time" class="shrink-0 font-mono text-[0.71875rem] text-fg-subtle tabular-nums">{{ formatActivity(session.last_activity_at) }}</span>
        </template>
      </span>
    </span>
  </RouterLink>
</template>
