<script setup lang="ts">
import { computed } from 'vue'
import AgentRunRow from '../agent/AgentRunRow.vue'
import { useOrgStore } from '../../../stores/org'
import type { Run } from '../../../types/org'

// The runs that worked on a task, newest first, each with the agent and a link to its conversation.
const props = defineProps<{ runs: Run[] }>()
const org = useOrgStore()
const ordered = computed(() => [...props.runs].sort((a, b) => b.started_at - a.started_at || b.id - a.id))
</script>

<template>
  <section aria-labelledby="task-runs-title" class="flex flex-col gap-2">
    <h2 id="task-runs-title" class="m-0 text-sm font-semibold">Execuções</h2>
    <p v-if="runs.length === 0" data-test="task-runs-empty" class="m-0 text-sm text-fg-subtle">Nenhuma execução ainda.</p>
    <ul v-else aria-labelledby="task-runs-title" class="m-0 flex list-none flex-col p-0">
      <AgentRunRow v-for="run in ordered" :key="run.id" :run="run" :agent-name="org.byId(run.agent_id)?.name ?? 'Agente removido'" />
    </ul>
  </section>
</template>
