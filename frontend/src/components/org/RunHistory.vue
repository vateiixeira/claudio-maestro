<script setup lang="ts">
import { computed } from 'vue'
import type { Run } from '../../types/org'
import { historyBars, historyLabel, type HistoryBar } from './runHistory'

// A strip of small bars with the last runs that ended, oldest first: a glance at how the agent has been doing.
const props = defineProps<{ runs: Run[] }>()

const bars = computed(() => historyBars(props.runs))
const label = computed(() => historyLabel(bars.value))

const BAR: Record<HistoryBar, string> = {
  ok: 'h-3.5 bg-primary/75',
  fail: 'h-3.5 bg-diff-del-fg',
  wait: 'h-3.5 bg-secondary',
  miss: 'h-[3px] bg-fg-subtle',
}
</script>

<template>
  <span v-if="bars.length > 0" data-test="run-history" role="img" :aria-label="label" class="inline-flex h-3.5 items-center gap-[3px]">
    <i
      v-for="(kind, index) in bars"
      :key="index"
      data-test="run-history-bar"
      :data-kind="kind"
      class="w-1.5 rounded-sm"
      :class="BAR[kind]"
    />
  </span>
</template>
