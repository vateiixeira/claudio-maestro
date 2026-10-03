<script setup lang="ts">
import { computed } from 'vue'
import IconChevron from '../icons/IconChevron.vue'
import IconWorkKind from '../icons/IconWorkKind.vue'
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
    <IconWorkKind data-test="work-icon" :kind="kind" :size="13" :class="iconTone" />
    <span class="cap w-[5.5rem] shrink-0" :class="tone.text">{{ label ?? LABEL[kind] }}</span>
    <span v-if="tag" data-test="work-tag" class="shrink-0 rounded-full bg-elevated px-2 py-0.5 font-mono text-[0.6875rem] text-fg-muted">{{ tag }}</span>
    <span data-test="work-desc" class="min-w-0 grow truncate text-[0.8125rem] text-fg" :class="{ 'font-mono': mono }"><slot name="desc">{{ desc }}</slot></span>
    <slot name="trail" />
    <slot name="status"><WorkStatus :status="status" :meta="meta" :elapsed="elapsed" /></slot>
    <slot name="actions" />
    <IconChevron v-if="open !== undefined" data-test="work-chevron" :open="open" :size="12" class="text-fg-subtle duration-(--motion-enter) ease-(--ease-maestro)" />
  </component>
</template>
