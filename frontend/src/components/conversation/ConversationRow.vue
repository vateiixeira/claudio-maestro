<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import BranchLabel from '../git/BranchLabel.vue'
import GroupTag from '../groups/GroupTag.vue'
import PlanBadge from '../plan/PlanBadge.vue'
import { errorMessage, markSessionSeen } from '../../api/http'
import { waitingReason } from '../../conversationList'
import { formatActivity } from '../../format'
import { planPosition, planVisible } from '../plan/planText'
import { displayStateLabels } from '../../sessionState'
import { repoLabel, useGitStore } from '../../stores/git'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import type { Session } from '../../types/api'

// One conversation in a list. `inbox` adds "Marcar como lida"; `compact` has no actions.
const props = withDefaults(defineProps<{ session: Session; variant?: 'inbox' | 'list' | 'compact' }>(), { variant: 'list' })
const emit = defineEmits<{ error: [message: string] }>()

const projects = useProjectsStore()
const git = useGitStore()
const sessions = useSessionsStore()

const project = computed(() => projects.byId(props.session.project_id))
const repo = computed(() => git.reposFor(props.session.project_id)[0])
const finished = computed(() => props.session.display_state === 'finished')
const reason = computed(() => waitingReason(props.session))
// The link's stretched ::after covers the badge, so the badge's own title never shows: repeat it here.
const planTitle = computed(() => (planVisible(props.session) ? planPosition(props.session.plan!) : undefined))
const busy = ref(false)

async function run(action: () => Promise<unknown>) {
  if (busy.value) return
  busy.value = true
  try {
    await action()
  } catch (e) {
    emit('error', errorMessage(e))
  } finally {
    busy.value = false
  }
}
const toggleFinished = () => run(() => sessions.setFinished(props.session.session_id, !finished.value))
const markRead = () => run(() => markSessionSeen(props.session.session_id))
</script>

<template>
  <div
    data-test="conversation-row"
    :data-unread="String(session.unread)"
    class="group relative flex min-h-11 items-center gap-3 rounded-md px-2 hover:bg-card focus-within:bg-card"
  >
    <span class="flex w-2 shrink-0 justify-center">
      <span v-if="session.unread" data-test="unread-dot" class="size-2 rounded-full bg-info" />
    </span>
    <DisplayStateIcon :display="session.display_state" />
    <!-- Not positioned, so the link's stretched ::after still covers the whole row. -->
    <div data-test="row-title" class="flex min-w-0 grow items-center gap-2">
      <RouterLink
        data-test="row-link"
        :to="{ name: 'session', params: { id: session.session_id } }"
        :title="planTitle"
        class="min-w-0 truncate no-underline after:absolute after:inset-0 after:rounded-md focus-visible:outline-none focus-visible:after:ring-2 focus-visible:after:ring-primary focus-visible:after:ring-inset"
        :class="[finished ? 'text-fg-muted' : 'text-fg', session.unread ? 'font-semibold' : 'font-normal']"
      >{{ session.title }}</RouterLink>
      <PlanBadge :session="session" />
      <GroupTag :group-id="session.group_id" />
    </div>
    <span class="sr-only">{{ displayStateLabels[session.display_state] }}{{ session.unread ? ', com novidade' : '' }}</span>
    <span v-if="reason" data-test="waiting-reason" class="max-w-64 shrink-0 truncate text-xs text-secondary-soft">{{ reason }}</span>
    <!-- Fixed widths, kept even when empty, so the columns line up from row to row. The actions float over the right end instead of taking room from them. -->
    <span data-test="row-project" class="hidden w-36 shrink-0 items-center gap-1.5 text-xs text-fg-muted md:flex">
      <template v-if="project">
        <span class="size-2 shrink-0 rounded-[3px]" :style="{ backgroundColor: project.color }" />
        <span class="truncate">{{ project.name }}</span>
      </template>
    </span>
    <span data-test="row-branch" class="hidden w-40 shrink-0 lg:flex">
      <BranchLabel v-if="repo" :text="repoLabel(repo)" muted />
    </span>
    <span class="w-20 shrink-0 text-right text-xs text-fg-muted">{{ formatActivity(session.last_activity_at) }}</span>
    <div
      v-if="variant !== 'compact'"
      data-test="row-actions"
      class="absolute inset-y-0 right-2 z-10 flex items-center gap-1 rounded-md bg-card pl-2 opacity-0 pointer-events-none group-hover:opacity-100 group-hover:pointer-events-auto group-focus-within:opacity-100 group-focus-within:pointer-events-auto focus-within:opacity-100 focus-within:pointer-events-auto [@media(hover:none)]:opacity-100 [@media(hover:none)]:pointer-events-auto"
    >
      <button
        v-if="variant === 'inbox' && session.unread"
        type="button"
        data-test="row-mark-read"
        class="h-8 rounded-md px-2 text-xs text-fg-muted hover:bg-elevated hover:text-fg disabled:opacity-40"
        :disabled="busy"
        :aria-label="`Marcar ${session.title} como lida`"
        @click="markRead"
      >Marcar como lida</button>
      <button
        v-if="finished"
        type="button"
        data-test="row-reopen"
        class="h-8 rounded-md px-2 text-xs font-medium text-primary-soft hover:bg-elevated disabled:opacity-40"
        :disabled="busy"
        :aria-label="`Reabrir ${session.title}`"
        @click="toggleFinished"
      >Reabrir</button>
      <button
        v-else
        type="button"
        data-test="row-finish"
        class="h-8 rounded-md px-2 text-xs text-fg-muted hover:bg-elevated hover:text-fg disabled:opacity-40"
        :disabled="busy"
        :aria-label="`Finalizar ${session.title}`"
        @click="toggleFinished"
      >Finalizar</button>
    </div>
  </div>
</template>
