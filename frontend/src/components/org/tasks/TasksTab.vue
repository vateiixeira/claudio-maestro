<script setup lang="ts">
// Shell: the tasks of the project (T3/T4 fill it in).
defineProps<{ projectId: number }>()
</script>

<template>
  <div data-test="tasks-tab" :data-project-id="projectId"><p>Em construção</p></div>
</template>
