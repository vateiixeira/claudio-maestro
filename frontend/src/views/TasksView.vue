<script setup lang="ts">
import TaskList from '../components/org/tasks/TaskList.vue'
import TasksPage from '../components/org/tasks/TasksPage.vue'
</script>

<template>
  <TasksPage title="Tarefas">
    <p class="m-0 -mt-3 text-sm text-fg-muted">As tarefas de todos os projetos. Para criar uma, abra a organização do projeto.</p>
    <TaskList sync-query />
  </TasksPage>
</template>
