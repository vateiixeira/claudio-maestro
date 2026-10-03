<script setup lang="ts">
import { computed } from 'vue'
import type { NodeKind } from '../../conversation/turns'
import type { RailAlign } from '../../conversation/railAlign'
import type { WorkKind } from '../../conversation/work'
import IconThink from '../icons/IconThink.vue'
import IconWorkKind from '../icons/IconWorkKind.vue'

// Decorative marker of one item in the turn's rail. Text and notices are a dot; reasoning and each
// kind of action are a ring with the icon of the kind (the same icon as the action's header, in its
// tone); running, waiting for the user (triangle with "!") and failed (circle with "×") look
// different in shape, not only in color, and the state wins over the kind. The card next to it says it all again for screen readers.
// `live` is for a node that arrives while the conversation is open: it pops in once.
const props = defineProps<{ kind: NodeKind; align?: RailAlign; live?: boolean }>()

const WORK_KINDS: Record<WorkKind, 'command' | 'file' | 'agent'> = {
  bash: 'command', tool: 'command', read: 'file', search: 'file', edit: 'file', agent: 'agent',
}
// Whole class names, so Tailwind finds them.
const TONE = {
  think: 'border-[color-mix(in_oklab,var(--color-type-think)_55%,transparent)] text-type-think',
  command: 'border-[color-mix(in_oklab,var(--color-type-command)_55%,transparent)] text-type-command',
  file: 'border-[color-mix(in_oklab,var(--color-type-file)_55%,transparent)] text-type-file',
  agent: 'border-[color-mix(in_oklab,var(--color-type-agent)_55%,transparent)] text-type-agent',
  waiting: 'border-[color-mix(in_oklab,var(--color-secondary)_55%,transparent)] text-secondary',
  error: 'text-diff-del-fg',
}
const DOT: Partial<Record<NodeKind, string>> = {
  text: 'bg-fg-muted', task: 'bg-fg-muted', info: 'bg-fg-subtle', warning: 'bg-secondary',
}

// Middle of the first line of the card next to the node, from the top of the item (px).
const CENTER: Record<RailAlign, number> = {
  text: 12, // running text (15px, leading 1.65) under pt-2
  thinking: 14, // py-1.5 + text-xs line (16px)
  notice: 19, // border + py-2 + 20px line
  group: 22, // 44px header
  card: 17, // cards with a py-2 header
}

const dot = computed(() => DOT[props.kind])
const workKind = computed(() => (props.kind in WORK_KINDS ? (props.kind as WorkKind) : null))
const ringSize = computed(() => (props.kind === 'thinking' ? 18 : 22))
const size = computed(() => (dot.value ? 7 : ringSize.value))
// The node's center sits on the middle of the card's first line.
const style = computed(() => ({ paddingTop: `${CENTER[props.align ?? 'card'] - size.value / 2}px` }))
const tone = computed(() => {
  if (props.kind === 'thinking') return TONE.think
  if (props.kind === 'waiting') return TONE.waiting
  if (props.kind === 'error') return TONE.error
  if (props.kind === 'running') return 'border-secondary'
  return workKind.value ? TONE[WORK_KINDS[workKind.value]] : ''
})
</script>

<template>
  <div data-test="rail-node" :data-kind="kind" aria-hidden="true" class="flex w-7 shrink-0 justify-center" :style="style">
    <span v-if="dot" data-test="rail-dot" class="size-[7px] rounded-full shadow-[0_0_0_4px_var(--color-surface)]" :class="[dot, live && 'animate-pop']" />
    <span
      v-else
      data-test="rail-ring"
      class="flex shrink-0 items-center justify-center rounded-full bg-surface"
      :class="[ringSize === 18 ? 'size-[18px]' : 'size-[22px]', kind === 'error' ? '' : 'border', tone, live && 'animate-pop']"
    >
      <IconThink v-if="kind === 'thinking'" :size="10" />
      <IconWorkKind v-else-if="workKind" :kind="workKind" :size="12" />
      <svg
        v-else-if="kind === 'running'"
        width="12"
        height="12"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2.6"
        stroke-linecap="round"
        class="shrink-0 animate-spin text-secondary motion-reduce:animate-none"
      >
        <path d="M12 3a9 9 0 1 1-9 9" />
      </svg>
      <!-- Failed is a circle with an "×" and waiting for the user a triangle with a "!": the difference is the shape, not only the color. -->
      <svg
        v-else-if="kind === 'error'"
        data-shape="circle-x"
        width="22"
        height="22"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
        class="shrink-0"
      >
        <circle cx="12" cy="12" r="10.5" />
        <path d="m9 9 6 6" />
        <path d="m15 9-6 6" />
      </svg>
      <svg
        v-else
        data-shape="triangle"
        width="12"
        height="12"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2.2"
        stroke-linecap="round"
        stroke-linejoin="round"
        class="shrink-0"
      >
        <path d="M12 3 2 20h20L12 3z" />
        <path d="M12 10v4" />
        <path d="M12 17h.01" />
      </svg>
    </span>
  </div>
</template>
