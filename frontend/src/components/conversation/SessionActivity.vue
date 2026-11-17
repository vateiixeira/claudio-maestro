<script setup lang="ts">
import { computed } from 'vue'
import type { Session } from '../../types/api'
import { sessionActivity } from '../../conversation/rowActivity'
import { planStopped } from '../plan/planText'
import IconAgents from '../icons/IconAgents.vue'
import IconTerminal from '../icons/IconTerminal.vue'
import PlanSegments from './PlanSegments.vue'

const props = defineProps<{ session: Session }>()

const activity = computed(() => sessionActivity(props.session))
const stopped = computed(() => planStopped(props.session))
</script>

<template>
  <span
    v-if="activity"
    data-test="session-activity"
    :data-kind="activity.kind"
    class="flex min-w-0 items-center gap-2 text-xs"
    :class="activity.kind === 'waiting' ? 'text-secondary-soft' : 'text-fg-muted'"
  >
    <PlanSegments v-if="activity.kind === 'plan' && session.plan" :plan="session.plan" :stopped="stopped" />
    <IconTerminal v-else-if="activity.kind === 'command'" :size="13" class="shrink-0 text-type-command" />
    <IconAgents v-else-if="activity.kind === 'subagent'" :size="13" class="shrink-0 text-type-agent" />
    <span class="min-w-0 truncate" :class="activity.kind === 'command' || activity.kind === 'action' ? 'font-mono' : ''">{{ activity.text }}</span>
  </span>
</template>
