<script setup lang="ts">
import { computed } from 'vue'
import { labelStyle } from '../../labelColor'
import type { Label } from '../../types/api'

const props = defineProps<{ label: Label; compact?: boolean }>()
const style = computed(() => labelStyle(props.label.color))
</script>

<template>
  <span
    data-test="label-badge"
    :data-slug="label.slug"
    :title="label.slug"
    :style="style"
    class="inline-block shrink-0 truncate rounded-full px-2 font-mono leading-[1.125rem]"
    :class="compact ? 'max-w-20 text-[0.625rem]' : 'max-w-40 text-[0.6875rem]'"
  >{{ label.slug }}</span>
</template>
