<script setup lang="ts">
import { computed } from 'vue'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import { planPosition, planVisible } from '../plan/planText'
import { needsYou } from '../../conversation/needsYou'
import { usePendingDecision } from '../../conversation/pendingDecision'
import { waitingReason } from '../../conversationList'
import { formatActivity } from '../../format'
import { displayStateLabels } from '../../sessionState'
import type { Project, Session } from '../../types/api'

// One "Agora" card; Allow/Deny when a tool permission is pending.
const props = defineProps<{ session: Session; project?: Project }>()

const decision = usePendingDecision(() => props.session)
const reason = computed(() => waitingReason(props.session) ?? displayStateLabels[props.session.display_state])
</script>

<template>
  <article data-test="now-card" class="flex flex-col gap-2 rounded-lg border border-line bg-panel p-4">
    <div class="flex items-center gap-2 text-xs text-fg-subtle">
      <span v-if="project" class="size-2 rounded-[3px]" :style="{ backgroundColor: project.color }" />
      {{ project?.name ?? '' }}
      <span class="grow" />
      {{ formatActivity(session.last_activity_at) }}
    </div>
    <RouterLink :to="{ name: 'session', params: { id: session.session_id } }" class="truncate font-semibold text-fg no-underline hover:underline">{{ session.title }}</RouterLink>
    <p v-if="session.plan && planVisible(session)" data-test="now-plan" class="m-0 truncate text-xs text-fg-muted">{{ planPosition(session.plan) }}</p>
    <div class="flex items-center gap-1.5 text-xs">
      <DisplayStateIcon :display="session.display_state" :size="11" :quiet="!needsYou(session)" />
      <span :class="session.display_state === 'waiting' ? (needsYou(session) ? 'text-secondary-soft' : 'text-fg-muted') : 'text-primary-soft'">{{ reason }}</span>
    </div>
    <p v-if="session.last_action" class="m-0 truncate font-mono text-xs text-fg-subtle">{{ session.last_action }}</p>
    <div v-if="decision.pending.value && !decision.answered.value" class="flex gap-2 pt-1">
      <button
        type="button"
        data-test="now-allow"
        :disabled="decision.sending.value !== null"
        class="h-9 grow rounded-md bg-secondary text-sm font-semibold text-secondary-fg disabled:opacity-60"
        :aria-label="`Permitir ${decision.pending.value.tool_name} em ${session.title}`"
        @click="decision.decide('allow_once')"
      >Permitir</button>
      <button
        type="button"
        data-test="now-deny"
        :disabled="decision.sending.value !== null"
        class="h-9 grow rounded-md border border-secondary/50 text-sm text-secondary-soft disabled:opacity-60"
        :aria-label="`Negar ${decision.pending.value.tool_name} em ${session.title}`"
        @click="decision.decide('deny')"
      >Negar</button>
    </div>
    <p v-if="decision.answered.value" role="status" class="m-0 text-xs text-fg-muted">Resposta enviada. Atualizando…</p>
    <p v-if="decision.error.value" role="alert" class="m-0 text-xs text-diff-del-fg">{{ decision.error.value }}</p>
  </article>
</template>
