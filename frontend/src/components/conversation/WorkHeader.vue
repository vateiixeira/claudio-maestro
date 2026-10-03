<script setup lang="ts">
import { computed } from 'vue'
import IconChevron from '../icons/IconChevron.vue'
import WorkStatus from './WorkStatus.vue'

type Kind = 'bash' | 'tool' | 'read' | 'search' | 'edit' | 'agent'
type Family = 'command' | 'file' | 'agent'

const props = withDefaults(
  defineProps<{
    kind: Kind
    /** Replaces the default label of the kind ("Escrita" for a Write). */
    label?: string
    /** A small chip before the description (the subagent type, the search tool). */
    tag?: string
    desc: string
    status: 'ok' | 'running' | 'error' | 'stopped' | 'idle'
    meta?: string
    elapsed?: string
    /** When set, the row shows a chevron that points down while open. */
    open?: boolean
    /** `button` makes the whole row the toggle. */
    as?: 'div' | 'button'
    /** The 9% fill of the kind; off when a card around the row already carries it. */
    tint?: boolean
    mono?: boolean
  }>(),
  // `open: undefined` keeps Vue from turning a missing prop into `false`: no `open` means no chevron.
  { as: 'div', tint: true, mono: false, open: undefined },
)

const FAMILY: Record<Kind, Family> = { bash: 'command', tool: 'command', read: 'file', search: 'file', edit: 'file', agent: 'agent' }
const LABEL: Record<Kind, string> = { bash: 'Comando', tool: 'Ferramenta', read: 'Leitura', search: 'Busca', edit: 'Edição', agent: 'Subagente' }
// Whole class names, so Tailwind finds them.
const TONE: Record<Family, { text: string; fill: string; hover: string }> = {
  command: {
    text: 'text-type-command',
    fill: 'bg-[color-mix(in_oklab,var(--color-type-command)_9%,transparent)]',
    hover: 'hover:bg-[color-mix(in_oklab,var(--color-type-command)_14%,transparent)]',
  },
  file: {
    text: 'text-type-file',
    fill: 'bg-[color-mix(in_oklab,var(--color-type-file)_9%,transparent)]',
    hover: 'hover:bg-[color-mix(in_oklab,var(--color-type-file)_14%,transparent)]',
  },
  agent: {
    text: 'text-type-agent',
    fill: 'bg-[color-mix(in_oklab,var(--color-type-agent)_9%,transparent)]',
    hover: 'hover:bg-[color-mix(in_oklab,var(--color-type-agent)_14%,transparent)]',
  },
}

const tone = computed(() => TONE[FAMILY[props.kind]])
const clickable = computed(() => props.as === 'button')
// State beats type: a failed action is red even in the tone of its kind.
const iconTone = computed(() => (props.status === 'error' ? 'text-diff-del-fg' : tone.value.text))
const rowClass = computed(() => [
  'flex min-h-[38px] items-center gap-2.5 px-3',
  props.tint ? tone.value.fill : '',
  props.tint && clickable.value ? tone.value.hover : '',
  clickable.value ? 'w-full cursor-pointer border-0 text-left text-fg focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary disabled:cursor-default' : '',
])
</script>

<template>
  <component :is="as" :type="clickable ? 'button' : undefined" data-test="work-header" :data-kind="kind" :class="rowClass">
    <svg
      data-test="work-icon"
      width="13"
      height="13"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
      class="shrink-0"
      :class="iconTone"
      aria-hidden="true"
    >
      <template v-if="kind === 'bash'"><path d="m4 17 6-6-6-6" /><path d="M12 19h8" /></template>
      <template v-else-if="kind === 'tool'"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94z" /></template>
      <template v-else-if="kind === 'read'"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6" /></template>
      <template v-else-if="kind === 'search'"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></template>
      <template v-else-if="kind === 'edit'"><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></template>
      <template v-else><rect x="4" y="8" width="16" height="12" rx="3" /><path d="M12 8V4" /><path d="M9 14h.01" /><path d="M15 14h.01" /></template>
    </svg>
    <span class="cap w-[5.5rem] shrink-0" :class="tone.text">{{ label ?? LABEL[kind] }}</span>
    <span v-if="tag" data-test="work-tag" class="shrink-0 rounded-full bg-elevated px-2 py-0.5 font-mono text-[0.6875rem] text-fg-muted">{{ tag }}</span>
    <span data-test="work-desc" class="min-w-0 grow truncate text-[0.8125rem] text-fg" :class="{ 'font-mono': mono }"><slot name="desc">{{ desc }}</slot></span>
    <slot name="trail" />
    <slot name="status"><WorkStatus :status="status" :meta="meta" :elapsed="elapsed" /></slot>
    <slot name="actions" />
    <IconChevron v-if="open !== undefined" data-test="work-chevron" :open="open" :size="12" class="text-fg-subtle" />
  </component>
</template>
