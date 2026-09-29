<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import { ApiError, answerPrompt, errorMessage } from '../../api/http'
import { formatActivity } from '../../format'
import { displayStateLabels } from '../../sessionState'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import type { Session } from '../../types/api'
import type { PromptDecision } from '../../types/conversation'

// One session in a list: opens it as a column, and finishes or reopens it.
const props = withDefaults(defineProps<{ session: Session; showProject?: boolean }>(), { showProject: false })
const emit = defineEmits<{ error: [message: string] }>()

const sessions = useSessionsStore()
const projects = useProjectsStore()
const project = computed(() => projects.byId(props.session.project_id))
const finished = computed(() => props.session.display_state === 'finished')
const busy = ref(false)
// Only sessions waiting for the user can be finished from the list.
const canFinish = computed(() => props.session.display_state === 'waiting')
const subtitle = computed(() => {
  if (props.session.awaiting_decision) return 'Pede sua decisão'
  if (props.session.state === 'error') return 'Erro'
  return displayStateLabels[props.session.display_state]
})

// Tool permission answered from the list, without opening the session.
const pending = computed(() => props.session.pending_permission ?? null)
const sending = ref<PromptDecision | null>(null)
const answeredPrompt = ref<string | null>(null)
const pendingError = ref<string | null>(null)
const pendingAnswered = computed(() => pending.value != null && answeredPrompt.value === pending.value.prompt_id)

async function decide(decision: PromptDecision): Promise<void> {
  const prompt = pending.value
  if (!prompt || sending.value) return
  sending.value = decision
  pendingError.value = null
  try {
    await answerPrompt(props.session.session_id, prompt.prompt_id, decision)
    answeredPrompt.value = prompt.prompt_id
  } catch (e) {
    // 409: already answered (maybe in another tab). Nothing to warn about.
    if (e instanceof ApiError && e.status === 409) answeredPrompt.value = prompt.prompt_id
    else pendingError.value = errorMessage(e)
  } finally {
    sending.value = null
  }
}

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
  <!-- Finished: compact row with title, date and "Reabrir". -->
  <div
    v-if="finished"
    data-test="finished-row"
    class="flex min-h-[52px] items-center gap-4 rounded-lg border border-line py-1 pr-2 pl-4"
    :data-unread="String(session.unread)"
  >
    <RouterLink
      data-test="session-row"
      :to="{ name: 'session', params: { id: session.session_id } }"
      class="flex min-w-0 grow items-center gap-2 text-fg no-underline hover:text-primary-soft"
    >
      <span v-if="showProject && project" class="size-2 shrink-0 rounded-[3px]" :style="{ backgroundColor: project.color }" :title="project.name" />
      <span data-test="open-session" class="truncate">{{ session.title }}</span>
    </RouterLink>
    <span class="shrink-0 text-xs text-fg-muted">{{ formatActivity(session.last_activity_at) }}</span>
    <button
      type="button"
      data-test="reopen"
      class="h-11 shrink-0 rounded-lg px-3.5 text-sm font-medium text-primary-soft hover:bg-elevated disabled:opacity-40"
      :disabled="busy"
      @click="toggle"
    >
      Reabrir
    </button>
  </div>
  <div
    v-else
    class="flex flex-col rounded-lg border bg-card"
    :class="session.awaiting_decision ? 'border-secondary/50' : session.display_state === 'running' ? 'border-primary/30' : 'border-line'"
    :data-unread="String(session.unread)"
  >
  <div class="flex items-center gap-2 pr-2">
    <RouterLink
      data-test="session-row"
      :to="{ name: 'session', params: { id: session.session_id } }"
      class="flex min-h-[52px] min-w-0 grow items-center gap-3 py-2 pl-4 text-fg no-underline"
      :class="{ 'pr-2': !canFinish }"
    >
      <DisplayStateIcon :display="session.display_state" />
      <span class="flex min-w-0 grow flex-col gap-0.5">
        <span v-if="showProject && project" class="flex items-center gap-1.5 text-xs text-fg-muted">
          <span class="size-2 shrink-0 rounded-[3px]" :style="{ backgroundColor: project.color }" />
          <span class="truncate">{{ project.name }}</span>
          <span v-if="!project.available" data-test="project-unavailable" class="shrink-0">pasta indisponível</span>
        </span>
        <span data-test="open-session" class="truncate" :class="session.unread ? 'font-semibold' : 'font-medium'">
          {{ session.title }}
        </span>
        <span
          class="font-mono text-xs"
          :class="session.awaiting_decision ? 'text-secondary-soft' : 'text-fg-muted'"
        >
          {{ subtitle }}
          <template v-if="session.unread"> · novidade</template>
        </span>
      </span>
      <span class="shrink-0 text-xs text-fg-muted">{{ formatActivity(session.last_activity_at) }}</span>
    </RouterLink>
    <button
      v-if="canFinish"
      type="button"
      data-test="finish"
      class="h-11 shrink-0 rounded-lg px-3.5 text-sm font-medium text-fg-muted hover:bg-elevated hover:text-fg disabled:opacity-40"
      :disabled="busy"
      @click="toggle"
    >
      Finalizar
    </button>
  </div>
  <div v-if="pending" data-test="pending-permission" class="flex flex-col gap-2.5 px-4 pt-1 pb-3">
    <p class="m-0 text-xs text-secondary-soft">
      Pede permissão para usar <span class="font-mono">{{ pending.tool_name }}</span>
    </p>
    <pre
      data-test="pending-summary"
      class="m-0 max-h-24 overflow-auto rounded-md border border-line bg-bg px-2.5 py-2 font-mono text-xs leading-relaxed whitespace-pre-wrap break-all text-fg"
    >{{ pending.summary }}</pre>
    <p v-if="pendingAnswered" data-test="pending-status" role="status" class="m-0 text-sm text-fg-muted">
      Resposta enviada. Atualizando…
    </p>
    <template v-else>
      <p v-if="pendingError" role="alert" class="m-0 text-sm text-diff-del-fg">{{ pendingError }}</p>
      <div class="flex gap-2">
        <button
          type="button"
          data-test="pending-allow"
          class="h-11 grow cursor-pointer rounded-lg border-none bg-secondary text-sm font-semibold text-secondary-fg disabled:cursor-default disabled:opacity-60"
          :disabled="sending !== null"
          :aria-label="`Permitir ${pending.tool_name} em ${session.title}`"
          @click="decide('allow_once')"
        >
          Permitir
        </button>
        <button
          type="button"
          data-test="pending-deny"
          class="h-11 grow cursor-pointer rounded-lg border border-secondary/50 bg-transparent text-sm font-medium text-secondary-soft disabled:cursor-default disabled:opacity-60"
          :disabled="sending !== null"
          :aria-label="`Negar ${pending.tool_name} em ${session.title}`"
          @click="decide('deny')"
        >
          Negar
        </button>
      </div>
    </template>
  </div>
  </div>
</template>
