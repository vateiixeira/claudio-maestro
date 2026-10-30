<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { agentRunFocus } from '../../org'
import { useOrgStore } from '../../stores/org'
import { useSessionsStore } from '../../stores/sessions'
import AgentStateIcon from '../org/AgentStateIcon.vue'

// Under the header of the main conversation of an agent: a fixed strip with the run or turn it has going on in
// another session, which the main conversation does not show. The whole strip opens that session. Orange when the
// session waits for the user; nothing when the agent is not running anything.
const props = defineProps<{ sessionId: string }>()
const org = useOrgStore()
const sessions = useSessionsStore()

const focus = computed(() => {
  const agent = org.isMainSession(props.sessionId)
  return agent ? agentRunFocus(agent, sessions.all) : null
})
</script>

<template>
  <RouterLink
    v-if="focus"
    data-test="agent-run-banner"
    :data-state="focus.waiting ? 'waiting' : 'running'"
    :to="{ name: 'session', params: { id: focus.sessionId } }"
    class="group flex min-h-9 shrink-0 items-center gap-2.5 border-b px-4 py-1.5 text-sm no-underline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary"
    :class="focus.waiting
      ? 'border-secondary/40 bg-secondary-tint text-fg hover:bg-secondary/20'
      : 'border-line bg-card/60 text-fg-muted hover:bg-card hover:text-fg'"
  >
    <AgentStateIcon :state="focus.waiting ? 'waiting' : 'busy'" :size="14" />
    <span class="min-w-0 grow truncate">
      <template v-if="focus.waiting"><span class="font-medium text-fg">{{ focus.title }}</span> espera sua resposta</template>
      <template v-else>Rodando agora: <span class="font-medium text-fg">{{ focus.title }}</span></template>
    </span>
    <svg class="shrink-0 transition-transform motion-safe:group-hover:translate-x-0.5" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
  </RouterLink>
</template>
