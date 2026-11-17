<script setup lang="ts">
import { computed } from 'vue'
import { formatRunningTime } from '../../format'
import { tokensLabel } from '../../conversation/liveTurn'
import { useSecondClock } from '../../secondClock'
import RailNode from './RailNode.vue'

// The proof of life of a running turn, as the last item of its rail: what it is doing, for how long
// and how much it has written, and under that the command that runs.
const props = defineProps<{
  activity: string
  /** When the turn began (Unix seconds); null when unknown. */
  startedAt: number | null
  /** Output tokens so far; 0 or missing while not known. */
  tokens?: number
  /** The command that runs, when the activity has a description. */
  detail?: string
}>()

const now = useSecondClock(true)
const meta = computed(() => {
  const parts: string[] = []
  if (props.startedAt != null) parts.push(formatRunningTime(now.value / 1000 - props.startedAt))
  const tokens = tokensLabel(props.tokens)
  if (tokens) parts.push(tokens)
  return parts.join(' · ')
})
</script>

<template>
  <div data-test="turn-live" class="m-0 flex min-w-0 items-start gap-3">
    <span data-test="turn-live-node" class="flex shrink-0"><RailNode kind="running" align="text" /></span>
    <div class="flex min-w-0 grow flex-col gap-0.5 pt-px">
      <p class="m-0 flex min-w-0 items-baseline gap-3 text-sm leading-6">
        <span data-test="turn-live-activity" class="min-w-0 truncate font-medium text-secondary-soft">{{ activity }}</span>
        <span v-if="meta" data-test="turn-live-meta" class="ml-auto shrink-0 font-mono text-xs text-fg-subtle">{{ meta }}</span>
      </p>
      <p v-if="detail" data-test="turn-live-detail" class="m-0 truncate font-mono text-xs text-fg-subtle">{{ detail }}</p>
    </div>
  </div>
</template>
