<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ name: string }>()
const parts = computed(() => {
  const slash = props.name.lastIndexOf('/')
  return slash > 0 ? { short: props.name.slice(slash + 1), parent: props.name.slice(0, slash) } : { short: props.name, parent: '' }
})
</script>

<template>
  <span class="flex min-w-0 flex-row items-baseline gap-2" :title="name">
    <span data-test="repo-short-name" class="min-w-0 truncate font-mono text-[0.8125rem] font-semibold text-fg">{{ parts.short }}</span>
    <span v-if="parts.parent" data-test="repo-parent-name" class="min-w-0 shrink-[3] truncate font-mono text-[0.6875rem] font-normal text-fg-muted">{{ parts.parent }}</span>
  </span>
</template>
