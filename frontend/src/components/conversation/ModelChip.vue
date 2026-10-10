<script setup lang="ts">
import { computed } from 'vue'
import { formatModelName } from '../../format'

// The model a subagent runs on, as a small chip; nothing when it is not known yet.
const props = defineProps<{ model?: string | null }>()
const label = computed(() => (props.model ? formatModelName(props.model) : ''))
</script>

<template>
  <span
    v-if="model"
    data-test="model-chip"
    :title="model"
    class="shrink-0 rounded-full border border-line px-1.5 py-px font-mono text-[0.625rem] text-fg-subtle"
  >{{ label }}</span>
</template>
