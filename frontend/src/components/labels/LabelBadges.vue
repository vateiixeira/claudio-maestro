<script setup lang="ts">
import { computed } from 'vue'
import { useLabelsStore } from '../../stores/labels'
import type { Label } from '../../types/api'
import LabelBadge from './LabelBadge.vue'

// `max` defaults to 3 (1 when `compact`); the rest is summed up as "+N".
const props = defineProps<{ ids?: number[] | null; compact?: boolean; max?: number }>()
const store = useLabelsStore()

// Ids the store does not know (a label removed in another tab) show nothing.
const known = computed<Label[]>(() =>
  (props.ids ?? []).map((id) => store.byId(id)).filter((label): label is Label => label !== undefined),
)
const limit = computed(() => props.max ?? (props.compact ? 1 : 3))
const shown = computed(() => known.value.slice(0, limit.value))
const hidden = computed(() => known.value.slice(limit.value))
</script>

<template>
  <span v-if="known.length" data-test="label-badges" class="flex min-w-0 shrink items-center gap-1 overflow-hidden">
    <LabelBadge v-for="label in shown" :key="label.id" :label="label" :compact="compact" />
    <span
      v-if="hidden.length"
      data-test="label-more"
      :title="hidden.map((label) => label.slug).join(', ')"
      class="shrink-0 font-mono text-[0.625rem] text-fg-subtle"
    >+{{ hidden.length }}</span>
  </span>
</template>
