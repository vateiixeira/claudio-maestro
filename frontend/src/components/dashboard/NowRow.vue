<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import ProjectTag from '../conversation/ProjectTag.vue'
import SessionActivity from '../conversation/SessionActivity.vue'
import { needsYou } from '../../conversation/needsYou'
import { usePendingDecision } from '../../conversation/pendingDecision'
import { formatActivity } from '../../format'
import type { Session } from '../../types/api'

// One line of "Agora": state, title, project, what it is doing and when; Allow/Deny when a tool permission is pending.
const props = defineProps<{ session: Session }>()

const decision = usePendingDecision(() => props.session)
</script>

<template>
  <div data-test="now-row" class="group relative border-b border-line hover:bg-panel focus-within:bg-panel">
    <div
      data-test="now-row-grid"
      class="grid min-h-[2.625rem] grid-cols-[0.875rem_minmax(0,1fr)_auto] items-center gap-x-3.5 gap-y-0.5 max-md:py-2 md:grid-cols-[0.875rem_minmax(0,18.75rem)_8.75rem_minmax(0,1fr)_3.875rem]"
    >
      <DisplayStateIcon :display="session.display_state" :size="13" :quiet="!needsYou(session)" />
      <RouterLink
        data-test="now-row-link"
        :to="{ name: 'session', params: { id: session.session_id } }"
        class="min-w-0 truncate text-sm font-medium text-fg no-underline after:absolute after:inset-0 focus-visible:outline-none focus-visible:after:ring-2 focus-visible:after:ring-primary focus-visible:after:ring-inset"
      >{{ session.title }}</RouterLink>
      <span data-test="now-row-project" class="flex min-w-0 max-md:col-span-2 max-md:col-start-2 max-md:row-start-2"><ProjectTag :project-id="session.project_id" /></span>
      <span data-test="now-row-activity" class="flex min-w-0 max-md:col-span-2 max-md:col-start-2 max-md:row-start-3 max-md:empty:hidden"><SessionActivity :session="session" /></span>
      <span data-test="now-row-time" class="whitespace-nowrap text-right font-mono text-[0.71875rem] text-fg-subtle tabular-nums max-md:col-start-3 max-md:row-start-1">{{ formatActivity(session.last_activity_at) }}</span>
    </div>
    <div v-if="decision.pending.value && !decision.answered.value" class="relative z-10 flex gap-2 pb-2 pl-[1.625rem]">
      <button
        type="button"
        data-test="now-allow"
        :disabled="decision.sending.value !== null"
        class="h-8 rounded-md bg-secondary px-4 text-sm font-semibold text-secondary-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:opacity-60"
        :aria-label="`Permitir ${decision.pending.value.tool_name} em ${session.title}`"
        @click="decision.decide('allow_once')"
      >Permitir</button>
      <button
        type="button"
        data-test="now-deny"
        :disabled="decision.sending.value !== null"
        class="h-8 rounded-md border border-secondary/50 px-4 text-sm text-secondary-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:opacity-60"
        :aria-label="`Negar ${decision.pending.value.tool_name} em ${session.title}`"
        @click="decision.decide('deny')"
      >Negar</button>
    </div>
    <p v-if="decision.answered.value" role="status" class="m-0 pb-2 pl-[1.625rem] text-xs text-fg-muted">Resposta enviada. Atualizando…</p>
    <p v-if="decision.error.value" role="alert" class="m-0 pb-2 pl-[1.625rem] text-xs text-diff-del-fg">{{ decision.error.value }}</p>
  </div>
</template>
