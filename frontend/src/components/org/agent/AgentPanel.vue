<script setup lang="ts">
// Shell: the panel of one agent (a later task fills it in). The tab inside the panel comes from `?aba=`
// (`definicao` is the one `NewAgentDialog` opens).
defineProps<{ agentId: number }>()
</script>

<template>
  <div data-test="agent-panel" :data-agent-id="agentId"><p>Em construção</p></div>
</template>
