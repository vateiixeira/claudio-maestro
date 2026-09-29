<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import BranchLabel from '../git/BranchLabel.vue'
import { errorMessage, markSessionSeen } from '../../api/http'
import { waitingReason } from '../../conversationList'
import { formatActivity } from '../../format'
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
    <RouterLink
      data-test="row-link"
      :to="{ name: 'session', params: { id: session.session_id } }"
      class="min-w-0 grow truncate no-underline after:absolute after:inset-0 focus-visible:outline-none"
      :class="[finished ? 'text-fg-muted' : 'text-fg', session.unread ? 'font-semibold' : 'font-normal']"
    >{{ session.title }}</RouterLink>
    <span class="sr-only">{{ displayStateLabels[session.display_state] }}{{ session.unread ? ', com novidade' : '' }}</span>
    <span v-if="reason" data-test="waiting-reason" class="max-w-64 shrink-0 truncate text-xs text-secondary-soft">{{ reason }}</span>
    <span v-if="project" data-test="row-project" class="hidden shrink-0 items-center gap-1.5 text-xs text-fg-muted md:flex">
      <span class="size-2 rounded-[3px]" :style="{ backgroundColor: project.color }" />
      <span class="max-w-40 truncate">{{ project.name }}</span>
    </span>
    <span v-if="repo" data-test="row-branch" class="hidden max-w-40 shrink-0 lg:flex">
      <BranchLabel :text="repoLabel(repo)" muted />
    </span>
    <span class="w-20 shrink-0 text-right text-xs text-fg-muted">{{ formatActivity(session.last_activity_at) }}</span>
    <div
      v-if="variant !== 'compact'"
      class="relative z-10 flex shrink-0 gap-1 opacity-0 group-hover:opacity-100 focus-within:opacity-100"
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
