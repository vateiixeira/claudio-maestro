<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import { errorMessage } from '../../api/http'
import { formatActivity } from '../../format'
import { sessionStateLabels } from '../../sessionState'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import type { Session } from '../../types/api'

// One session in a list: opens it as a column, and finishes or reopens it.
const props = withDefaults(defineProps<{ session: Session; showProject?: boolean }>(), { showProject: false })
const emit = defineEmits<{ error: [message: string] }>()

const sessions = useSessionsStore()
const projects = useProjectsStore()
const project = computed(() => projects.byId(props.session.project_id))
const finished = computed(() => props.session.display_state === 'finished')
const busy = ref(false)

async function toggle(): Promise<void> {
  busy.value = true
  try {
    await sessions.setFinished(props.session.session_id, !finished.value)
  } catch (e) {
    emit('error', errorMessage(e))
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div
    class="flex items-center gap-2 rounded-lg border bg-card pr-2"
    :class="session.awaiting_decision ? 'border-secondary/50' : session.display_state === 'running' ? 'border-primary/30' : 'border-line'"
    :data-unread="String(session.unread)"
  >
    <RouterLink
      data-test="session-row"
      :to="{ name: 'session', params: { id: session.session_id } }"
      class="flex min-h-[52px] min-w-0 grow items-center gap-3 py-2 pl-4 text-fg no-underline"
    >
      <DisplayStateIcon :display="session.display_state" />
      <span class="flex min-w-0 grow flex-col gap-0.5">
        <span v-if="showProject && project" class="flex items-center gap-1.5 text-xs text-fg-muted">
          <span class="size-2 shrink-0 rounded-[3px]" :style="{ backgroundColor: project.color }" />
          <span class="truncate">{{ project.name }}</span>
        </span>
        <span data-test="open-session" class="truncate" :class="session.unread ? 'font-semibold' : 'font-medium'">
          {{ session.title }}
        </span>
        <span
          class="font-mono text-xs"
          :class="session.awaiting_decision ? 'text-secondary-soft' : 'text-fg-muted'"
        >
          {{ session.awaiting_decision ? 'Pede sua decisão' : sessionStateLabels[session.state] }}
          <template v-if="session.unread"> · novidade</template>
        </span>
      </span>
      <span class="shrink-0 text-xs text-fg-muted">{{ formatActivity(session.last_activity_at) }}</span>
    </RouterLink>
    <button
      type="button"
      :data-test="finished ? 'reopen' : 'finish'"
      class="h-11 shrink-0 rounded-lg px-3.5 text-sm font-medium hover:bg-elevated disabled:opacity-40"
      :class="finished ? 'text-primary-soft' : 'text-fg-muted hover:text-fg'"
      :disabled="busy"
      @click="toggle"
    >
      {{ finished ? 'Reabrir' : 'Finalizar' }}
    </button>
  </div>
</template>
