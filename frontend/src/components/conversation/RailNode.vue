<script setup lang="ts">
import { computed } from 'vue'
import type { NodeKind } from '../../conversation/turns'
import type { RailAlign } from '../../conversation/railAlign'

// Decorative marker of one item in the turn's rail: a small dot for every kind, only the color
// changes. The card itself names the type.
const props = defineProps<{ kind: NodeKind; align?: RailAlign }>()

// Pushes the dot down to the middle of the first line of the card next to it. It depends on the
// card, not on the state: running and error fit any card.
const OFFSET: Record<RailAlign, string> = {
  text: 'pt-[18px]', // bubble padding + first text line
  group: 'pt-[18px]', // 44px header
  agent: 'pt-[17px]', // card with a py-2.5 header
  notice: 'pt-[15px]', // border + py-2 + 20px line
  bash: 'pt-1.5', // loose one-line header (text-sm leading-5)
  thinking: 'pt-1', // text-xs line
  card: 'pt-[13px]', // cards with a py-2 header
}
const offset = computed(() => OFFSET[props.align ?? 'card'])

const color = computed(() => {
  switch (props.kind) {
    case 'running': return 'bg-secondary animate-pulse motion-reduce:animate-none'
    case 'error': return 'bg-diff-del-fg'
    case 'warning': return 'bg-secondary'
    case 'text': return 'bg-fg'
    case 'info': case 'thinking': return 'bg-fg-subtle'
    default: return 'bg-fg-muted'
  }
})
</script>

<template>
  <div data-test="rail-node" :data-kind="kind" aria-hidden="true" class="flex w-7 shrink-0 justify-center" :class="offset">
    <span data-test="rail-dot" class="size-2 rounded-full shadow-[0_0_0_4px_var(--color-surface)]" :class="color" />
  </div>
</template>
