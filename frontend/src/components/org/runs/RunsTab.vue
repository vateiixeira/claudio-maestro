<script setup lang="ts">
// Shell: the runs of all the agents of the project (a later task fills it in; it uses `AgentRunRow`).
defineProps<{ projectId: number }>()
</script>

<template>
  <div data-test="runs-tab" :data-project-id="projectId"><p>Em construção</p></div>
</template>
