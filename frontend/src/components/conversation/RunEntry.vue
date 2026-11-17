<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import PromptCards from './PromptCards.vue'
import RunSteps from './RunSteps.vue'
import TextBlock from './TextBlock.vue'
import TurnLiveLine from './TurnLiveLine.vue'
import { cancelAgentRun, errorMessage } from '../../api/http'
import { IN_FLIGHT } from '../../conversation/agentTimeline'
import { liveActivity } from '../../conversation/liveTurn'
import { buildItemTree } from '../../conversation/subagents'
import { buildTurns } from '../../conversation/turns'
import { useSessionConversation } from '../../conversation/useSessionConversation'
import { waitingIdsOf } from '../../conversation/waiting'
import { formatRunningTime } from '../../format'
import { OUTCOME_LABELS, SOURCE_LABELS, formatRunDate } from '../../org'
import { useConversationStore } from '../../stores/conversation'
import type { TextItem } from '../../types/conversation'
import type { Run } from '../../types/org'

/**
 * One run of the agent as an entry of its conversation: a thin marker (what woke it, when, how it
 * ended), the result in the agent's own words, and, while it runs, its live line and the requests it
 * waits on. The steps open in place; "Abrir sozinha" goes to the run's own session.
 */
const props = defineProps<{ run: Run; routineName?: string | null }>()

const conversations = useConversationStore()

const inFlight = computed(() => IN_FLIGHT.has(props.run.outcome))
// Only a run in flight follows its session; a finished one shows the stored summary and loads nothing.
const followed = computed(() => (inFlight.value ? props.run.session_id : null))
const { conv } = useSessionConversation(followed)

const label = computed(() => (props.routineName ? `Rotina "${props.routineName}"` : SOURCE_LABELS[props.run.source]))
const outcomeLabel = computed(() => {
  if (props.run.outcome === 'waiting') return 'Aguardando você'
  return inFlight.value ? 'Rodando agora' : OUTCOME_LABELS[props.run.outcome]
})
const outcomeTone = computed(() => {
  if (props.run.outcome === 'waiting') return 'text-secondary-soft'
  if (props.run.outcome === 'failed') return 'text-diff-del-fg'
  return inFlight.value ? 'text-primary-soft' : 'text-fg-subtle'
})
const duration = computed(() =>
  props.run.ended_at === null ? null : formatRunningTime(props.run.ended_at - props.run.started_at),
)

const resultItem = computed<TextItem | null>(() => {
  const text = props.run.summary
  if (inFlight.value || !text) return null
  return { type: 'text', id: `run-${props.run.id}-result`, text, streaming: false, parent_tool_use_id: null }
})

// The live line: what the run's session does now.
const sessionActive = computed(() => conv.value?.state === 'running' || conv.value?.state === 'awaiting_decision')
const waitingIds = computed(() => waitingIdsOf(conv.value?.items ?? [], conv.value?.prompts ?? []))
const liveText = computed(() => {
  const current = conv.value
  if (!current) return 'Iniciando'
  const turns = buildTurns(buildItemTree(current.items).top)
  const last = turns[turns.length - 1]
  if (!last) return current.prompts.length ? 'esperando você' : 'Pensando'
  return liveActivity(last, sessionActive.value, waitingIds.value, current.prompts.length > 0)
})

const stepsOpen = ref(false)
// A different run in the same slot starts closed.
watch(() => props.run.id, () => { stepsOpen.value = false })

const cancelling = ref(false)
const cancelError = ref<string | null>(null)
async function cancel() {
  if (cancelling.value) return
  cancelling.value = true
  cancelError.value = null
  try {
    await cancelAgentRun(props.run.agent_id, props.run.id)
  } catch (e) {
    cancelError.value = errorMessage(e)
  } finally {
    cancelling.value = false
  }
}
const control = 'cursor-pointer rounded border-none bg-transparent p-0 text-xs text-info-soft no-underline hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary'
</script>

<template>
  <section
    data-test="run-entry"
    :data-run-id="run.id"
    :data-run-session="run.session_id ?? undefined"
    tabindex="-1"
    class="flex scroll-mt-11 flex-col gap-2.5 focus-visible:outline-2 focus-visible:outline-primary"
  >
    <div data-test="run-entry-marker" class="mt-1.5 flex items-center gap-2.5">
      <span class="cap min-w-0 truncate text-fg-subtle">{{ label }}</span>
      <RouterLink v-if="run.task_id !== null" :to="`/tarefas/${run.task_id}`" class="shrink-0 rounded font-mono text-xs text-info-soft hover:underline focus-visible:outline-2 focus-visible:outline-primary">#{{ run.task_id }}</RouterLink>
      <time :datetime="new Date(run.started_at * 1000).toISOString()" class="shrink-0 font-mono text-xs text-fg-subtle">{{ formatRunDate(run.started_at) }}</time>
      <span class="shrink-0 text-xs" :class="outcomeTone">{{ outcomeLabel }}</span>
      <span v-if="duration" class="shrink-0 font-mono text-xs text-fg-subtle">{{ duration }}</span>
      <span aria-hidden="true" class="h-px grow bg-line" />
    </div>

    <p v-if="run.reason && !inFlight" data-test="run-entry-reason" class="m-0 text-sm text-fg-muted [overflow-wrap:anywhere]">{{ run.reason }}</p>
    <div v-if="resultItem" data-test="run-entry-result"><TextBlock :item="resultItem" /></div>

    <template v-if="inFlight && run.session_id">
      <TurnLiveLine data-test="run-entry-live" :activity="liveText" :started-at="conv?.runningSince ?? run.started_at" :tokens="conv?.turnTokens" />
      <PromptCards
        v-if="conv"
        :session-id="conv.sessionId"
        :prompts="conv.prompts"
        :is-live="() => false"
        @resolved="conversations.resolvePrompt(conv.sessionId, $event)"
      />
    </template>

    <div v-if="run.session_id" class="flex flex-wrap items-center gap-x-3 gap-y-1">
      <button
        v-if="inFlight && run.session_id"
        type="button"
        data-test="run-entry-cancel"
        :aria-disabled="cancelling"
        :class="[control, 'aria-disabled:cursor-default aria-disabled:opacity-60']"
        @click="cancel"
      >Cancelar</button>
      <button
        type="button"
        data-test="run-entry-steps-toggle"
        :aria-expanded="stepsOpen"
        :class="control"
        @click="stepsOpen = !stepsOpen"
      >{{ stepsOpen ? 'Esconder passo a passo' : 'Ver passo a passo' }}</button>
      <RouterLink data-test="run-entry-open" :to="{ name: 'session', params: { id: run.session_id } }" :class="control">Abrir sozinha</RouterLink>
      <span v-if="cancelError" role="alert" class="text-xs text-diff-del-fg">{{ cancelError }}</span>
    </div>
    <RunSteps v-if="stepsOpen && run.session_id" :session-id="run.session_id" :prompts="!inFlight" />
  </section>
</template>
