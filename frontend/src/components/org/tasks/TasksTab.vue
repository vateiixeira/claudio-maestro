<script setup lang="ts">
import { ref } from 'vue'
import NewTaskForm from './NewTaskForm.vue'
import TaskList from './TaskList.vue'
import { BTN_PRIMARY } from '../styles'

// The tasks of a project: filters, the list and a form for a new one.
defineProps<{ projectId: number }>()

const creating = ref(false)
</script>

<template>
  <div data-test="tasks-tab" :data-project-id="projectId" class="flex min-w-0 flex-col gap-4">
    <div v-if="!creating" class="flex justify-end">
      <button type="button" data-test="new-task" :class="BTN_PRIMARY" @click="creating = true">Nova tarefa</button>
    </div>
    <NewTaskForm v-if="creating" :project-id="projectId" @created="creating = false" @cancel="creating = false" />
    <TaskList :project-id="projectId" />
  </div>
</template>
