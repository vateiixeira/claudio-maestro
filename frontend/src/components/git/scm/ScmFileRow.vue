<script setup lang="ts">
import type { RepoFile } from '../../../types/api'

const props = defineProps<{ file: RepoFile; open: boolean; readOnly: boolean; disabled: boolean }>()
const emit = defineEmits<{ toggle: []; editor: []; discard: []; stage: []; unstage: [] }>()

const name = () => props.file.path.slice(props.file.path.lastIndexOf('/') + 1)
const folder = () => (props.file.path.includes('/') ? props.file.path.slice(0, props.file.path.lastIndexOf('/')) : '')
const letter = () => (props.file.status === 'conflict' ? '!' : (props.file.kind ?? 'M'))
const LETTER_CLASS: Record<string, string> = { M: 'text-fg-muted', A: 'text-diff-add-fg', D: 'text-diff-del-fg', R: 'text-info-soft', '!': 'text-secondary' }
const iconButton = 'flex size-[22px] items-center justify-center rounded text-fg-muted hover:bg-card hover:text-fg disabled:opacity-50'
</script>

<template>
  <div
    data-test="scm-file"
    :data-path="file.path"
    class="group flex h-6 items-center gap-1.5 rounded pr-1 hover:bg-elevated focus-within:bg-elevated"
    :class="{ 'bg-card': open }"
  >
    <button type="button" data-test="file-open" :aria-expanded="open" :title="file.path" class="flex min-w-0 grow items-center gap-1.5 pl-1 text-left" @click="emit('toggle')">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="shrink-0 text-fg-subtle"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /></svg>
      <span class="min-w-0 truncate"><span class="text-[0.8125rem] text-fg">{{ name() }}</span><span v-if="folder()" class="ml-2 font-mono text-[0.6875rem] text-fg-subtle">{{ folder() }}</span></span>
    </button>
    <span class="flex shrink-0 items-center w-0 overflow-hidden opacity-0 group-hover:w-auto group-hover:opacity-100 group-focus-within:w-auto group-focus-within:opacity-100">
      <button type="button" data-test="file-editor" :class="iconButton" aria-label="Abrir no editor" title="Abrir no editor" @click="emit('editor')">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 3h6v6" /><path d="M10 14 21 3" /><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /></svg>
      </button>
      <template v-if="!readOnly">
        <slot name="actions">
          <button type="button" data-test="file-discard" :class="iconButton" :disabled="disabled" aria-label="Descartar alterações" title="Descartar alterações" @click="emit('discard')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5" /></svg>
          </button>
          <button v-if="file.status === 'staged'" type="button" data-test="file-unstage" :class="iconButton" :disabled="disabled" aria-label="Tirar da preparação" title="Tirar da preparação" @click="emit('unstage')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><line x1="5" y1="12" x2="19" y2="12" /></svg>
          </button>
          <button v-else type="button" data-test="file-stage" :class="iconButton" :disabled="disabled" aria-label="Preparar" title="Preparar" @click="emit('stage')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
          </button>
        </slot>
      </template>
    </span>
    <span data-test="file-letter" class="w-3 shrink-0 text-center font-mono text-xs font-semibold" :class="LETTER_CLASS[letter()]" :title="file.status === 'conflict' ? 'Em conflito' : undefined">{{ letter() }}</span>
  </div>
</template>
