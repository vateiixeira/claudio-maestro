<script setup lang="ts">
import { computed, watch } from 'vue'
import type { SuggestionItem, SuggestionStatus } from '../../conversation/useComposerSuggestions'
import type { TriggerKind } from '../../conversation/suggestions'

const props = withDefaults(
  defineProps<{
    id: string
    items: SuggestionItem[]
    active: number
    status: SuggestionStatus
    error: string | null
    kind: TriggerKind
    optionId: (index: number) => string
    placement?: 'above' | 'below'
  }>(),
  { placement: 'above' },
)
const emit = defineEmits<{ choose: [index: number]; hover: [index: number] }>()

// Shown as a single disabled option when the list has nothing to offer.
const stateText = computed(() => {
  if (props.items.length) return null
  if (props.status === 'loading') return props.kind === 'command' ? 'Carregando…' : 'Buscando…'
  if (props.status === 'error') return props.error ?? ''
  return props.kind === 'command' ? 'Nenhum comando' : 'Nenhum arquivo encontrado'
})

watch(
  () => props.active,
  () => {
    // jsdom has no scrollIntoView.
    document.getElementById(props.optionId(props.active))?.scrollIntoView?.({ block: 'nearest' })
  },
)
</script>

<template>
  <ul
    :id="id"
    role="listbox"
    aria-label="Sugestões"
    class="absolute left-0 right-0 z-20 max-h-72 overflow-y-auto rounded-lg border border-line-strong bg-panel p-1 shadow-lg"
    :class="placement === 'above' ? 'bottom-full mb-1' : 'top-full mt-1'"
    @mousedown.prevent
  >
    <li
      v-for="(item, i) in items"
      :id="optionId(i)"
      :key="item.key"
      role="option"
      :aria-selected="i === active"
      class="flex cursor-pointer items-baseline gap-2 rounded-md px-2.5 py-1.5 text-sm text-fg"
      :class="{ 'bg-elevated': i === active }"
      @mouseenter="emit('hover', i)"
      @click="emit('choose', i)"
    >
      <template v-if="item.kind === 'file'">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 self-center text-fg-muted" aria-hidden="true"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6" /></svg>
        <span class="shrink-0 text-fg">{{ item.label }}</span>
        <span class="min-w-0 truncate text-xs text-fg-muted">{{ item.detail }}</span>
      </template>
      <template v-else-if="item.kind === 'directory'">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 self-center stroke-fg-muted" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /></svg>
        <span class="min-w-0 truncate text-fg">{{ item.label }}</span>
      </template>
      <template v-else>
        <span class="font-mono">{{ item.label }}</span>
        <span class="font-mono text-xs text-fg-muted">{{ item.hint }}</span>
        <span class="min-w-0 truncate text-xs text-fg-muted">{{ item.detail }}</span>
      </template>
    </li>
    <li v-if="stateText !== null" role="option" aria-disabled="true" class="px-2.5 py-1.5 text-sm text-fg-muted">
      {{ stateText }}
    </li>
  </ul>
</template>
