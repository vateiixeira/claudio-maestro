<script setup lang="ts">
import { computed } from 'vue'
import { projectInitials } from '../../projectInitials'
import type { Project } from '../../types/api'

const props = defineProps<{ project: Project }>()
const initials = computed(() => projectInitials(props.project.name))
</script>

<template>
  <span
    data-test="project-badge"
    :title="project.name"
    class="inline-flex h-3.5 min-w-[18px] shrink-0 items-center justify-center rounded-[3px] px-0.5 text-[9px] leading-none font-semibold text-bg"
    :style="{ backgroundColor: project.color }"
  >{{ initials }}</span>
</template>
