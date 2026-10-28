import { computed, watch, type Ref } from 'vue'
import { useOrgStore } from '../../stores/org'
import { useSessionsStore } from '../../stores/sessions'

/**
 * Which agent and task a conversation belongs to. A session an agent started that is not its main conversation is a
 * run, and the run says the task it works on. The runs of the agent are loaded here when they are not yet, so the
 * header and the thread agree without depending on each other. The main conversation and ordinary ones have no
 * agent here (`agentId` null).
 */
export function useRunTask(sessionId: Ref<string>) {
  const org = useOrgStore()
  const sessions = useSessionsStore()

  const agentId = computed(() => (org.isMainSession(sessionId.value) ? null : sessions.find(sessionId.value)?.agent_id ?? null))
  const agent = computed(() => (agentId.value !== null ? org.byId(agentId.value) : undefined))
  const taskId = computed(() => (agentId.value !== null ? org.runsOf(agentId.value).find((run) => run.session_id === sessionId.value)?.task_id ?? null : null))

  watch(
    () => (agentId.value !== null && org.runs[agentId.value] === undefined ? agentId.value : null),
    (id) => {
      // The task badge is decoration: a failure only hides it (the agent panel shows the error when it matters).
      if (id !== null) void org.loadRuns(id).catch(() => {})
    },
    { immediate: true },
  )

  return { agentId, agent, taskId }
}
