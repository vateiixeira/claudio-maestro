<script setup lang="ts">
import { computed } from 'vue'
import { formatRunningTime } from '../../format'
import { tokensLabel } from '../../conversation/liveTurn'
import { useSecondClock } from '../../secondClock'

// The proof of life of a running turn: what it is doing, for how long and how much it has written.
const props = defineProps<{
  activity: string
  /** When the turn began (Unix seconds); null when unknown. */
  startedAt: number | null
  /** Output tokens so far; 0 or missing while not known. */
  tokens?: number
}>()

const now = useSecondClock(true)
const meta = computed(() => {
  const parts: string[] = []
  if (props.startedAt != null) parts.push(formatRunningTime(now.value / 1000 - props.startedAt))
  const tokens = tokensLabel(props.tokens)
  if (tokens) parts.push(tokens)
  return parts.map((part) => ` · ${part}`).join('')
})
</script>

<template>
  <p data-test="turn-live" class="m-0 flex min-w-0 items-center gap-2 font-mono text-[0.6875rem]">
    <span aria-hidden="true" class="flex shrink-0 items-center gap-[3px]">
      <span
        v-for="n in 3"
        :key="n"
        data-test="turn-live-dot"
        aria-hidden="true"
        class="size-1 rounded-full bg-secondary animate-pulse motion-reduce:animate-none"
        :style="{ animationDelay: `${(n - 1) * 200}ms` }"
      />
    </span>
    <span class="min-w-0 truncate">
      <span data-test="turn-live-activity" class="text-secondary-soft">{{ activity }}</span><span data-test="turn-live-meta" class="text-fg-subtle">{{ meta }}</span>
    </span>
  </p>
</template>
