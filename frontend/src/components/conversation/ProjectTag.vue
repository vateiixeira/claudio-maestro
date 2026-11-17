<script setup lang="ts">
import { computed } from 'vue'
import { useProjectsStore } from '../../stores/projects'

const props = defineProps<{ projectId: number | null | undefined; branch?: string | null }>()

const projects = useProjectsStore()
const project = computed(() => (props.projectId == null ? undefined : projects.byId(props.projectId)))
</script>

<template>
  <span v-if="project" data-test="project-tag" class="flex min-w-0 flex-col">
    <span class="flex min-w-0 items-center gap-1.5 text-xs text-fg-muted">
      <span class="size-2 shrink-0 rounded-[2px]" :style="{ backgroundColor: project.color }" />
      <span class="truncate">{{ project.name }}</span>
    </span>
    <span v-if="branch" data-test="project-tag-branch" class="truncate font-mono text-xs text-fg-subtle">{{ branch }}</span>
  </span>
</template>
