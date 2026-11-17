<script setup lang="ts">
import { computed } from 'vue'
import IconChevron from '../icons/IconChevron.vue'
import ModelChip from './ModelChip.vue'
import IconWorkKind from '../icons/IconWorkKind.vue'
import WorkStatus from './WorkStatus.vue'

type Kind = 'bash' | 'tool' | 'read' | 'search' | 'edit' | 'agent'
type Family = 'command' | 'file' | 'agent'

type Status = 'ok' | 'running' | 'waiting' | 'error' | 'stopped' | 'idle'

const props = withDefaults(
  defineProps<{
    kind: Kind
    /** Replaces the default label of the kind ("Escrita" for a Write). */
    label?: string
    /** A small chip before the description (the subagent type, the search tool). */
    tag?: string
    /** The model of a subagent, in a smaller chip after the tag. */
    model?: string | null
    desc: string
    status: Status
    meta?: string
    elapsed?: string
    /** When set, the row shows a chevron that points down while open. */
    open?: boolean
    /** `button` makes the whole row the toggle. */
    as?: 'div' | 'button'
    /** The 9% fill of the kind; off when a card around the row already carries it. */
    tint?: boolean
    mono?: boolean
    /** A row inside a grouped work block: a status slot instead of the kind icon and label, and the command in its own column. */
    grouped?: boolean
    /** The command shown after the description (grouped rows only). */
    command?: string
  }>(),
  // `open: undefined` keeps Vue from turning a missing prop into `false`: no `open` means no chevron.
  { as: 'div', tint: true, mono: false, grouped: false, command: undefined, open: undefined },
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

// The grouped slot's color follows the state; ok, idle and stopped stay neutral (the pip).
const SLOT_TONE: Record<Status, string> = {
  ok: '',
  idle: '',
  stopped: '',
  error: 'text-diff-del-fg',
  running: 'text-secondary-soft',
  waiting: 'text-secondary',
}

const tone = computed(() => TONE[FAMILY[props.kind]])
const clickable = computed(() => props.as === 'button')
// State beats type: a failed action is red even in the tone of its kind.
const iconTone = computed(() => (props.status === 'error' ? 'text-diff-del-fg' : tone.value.text))
const showTint = computed(() => props.tint && !props.grouped)
const rowClass = computed(() => [
  props.grouped ? 'flex min-h-9 items-center gap-3 px-3.5' : 'flex min-h-[38px] items-center gap-2.5 px-3',
  showTint.value ? tone.value.fill : '',
  showTint.value && clickable.value ? tone.value.hover : '',
  props.grouped && clickable.value ? 'hover:bg-card' : '',
  clickable.value ? 'w-full cursor-pointer border-0 text-left text-fg focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary disabled:cursor-default' : '',
])
</script>

<template>
  <component :is="as" :type="clickable ? 'button' : undefined" data-test="work-header" :data-kind="kind" :class="rowClass">
    <span v-if="grouped" data-test="work-slot" :data-status="status" class="flex w-3.5 shrink-0 justify-center" :class="SLOT_TONE[status]">
      <svg v-if="status === 'error'" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
      <svg v-else-if="status === 'running'" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" class="animate-spin motion-reduce:animate-none" aria-hidden="true"><path d="M12 3a9 9 0 1 1-9 9" stroke-linecap="round" /></svg>
      <svg v-else-if="status === 'waiting'" data-shape="triangle" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3 2 20h20L12 3z" /><path d="M12 10v4" /><path d="M12 17h.01" /></svg>
      <span v-else data-test="work-pip" class="size-1 rounded-full bg-line-strong" aria-hidden="true" />
    </span>
    <template v-else>
      <IconWorkKind data-test="work-icon" :kind="kind" :size="13" :class="iconTone" />
      <span class="cap w-[5.5rem] shrink-0" :class="tone.text">{{ label ?? LABEL[kind] }}</span>
    </template>
    <span v-if="tag" data-test="work-tag" :title="tag" class="min-w-0 max-w-[10rem] truncate rounded-full bg-elevated px-2 py-0.5 font-mono text-[0.6875rem] text-fg-muted">{{ tag }}</span>
    <ModelChip :model="model" />
    <span
      data-test="work-desc"
      class="min-w-0 truncate text-[0.8125rem] text-fg"
      :class="[grouped && command ? 'max-w-[45%] shrink-0' : 'grow basis-0', { 'font-mono': mono }]"
    ><slot name="desc">{{ desc }}</slot></span>
    <span v-if="grouped && command" data-test="work-command" :title="command" class="min-w-0 grow basis-0 truncate font-mono text-xs text-fg-muted">{{ command }}</span>
    <slot name="trail" />
    <slot name="status"><WorkStatus :status="status" :meta="meta" :elapsed="elapsed" :iconless="grouped" /></slot>
    <slot name="actions" />
    <IconChevron v-if="open !== undefined" data-test="work-chevron" :open="open" :size="12" class="text-fg-subtle duration-(--motion-enter) ease-(--ease-maestro)" />
  </component>
</template>
