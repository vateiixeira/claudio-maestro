<script setup lang="ts">
import { nextTick, ref } from 'vue'
import QuickTaskBar from '../components/org/tasks/QuickTaskBar.vue'
import TaskList from '../components/org/tasks/TaskList.vue'
import TasksPage from '../components/org/tasks/TasksPage.vue'

const quickProject = ref<number | null>(null)
const bar = ref<InstanceType<typeof QuickTaskBar> | null>(null)

// "Nova tarefa" of a project in the empty list: the project goes to the bar and the title gets the focus.
async function startTask(projectId: number): Promise<void> {
  quickProject.value = projectId
  await nextTick()
  bar.value?.focus()
}
</script>

<template>
  <TasksPage title="Tarefas">
    <p class="m-0 -mt-3 text-sm text-fg-muted">O trabalho entregue às organizações de todos os projetos.</p>
    <QuickTaskBar ref="bar" v-model:project-id="quickProject" />
    <TaskList sync-query @new-task="startTask" />
  </TasksPage>
</template>
