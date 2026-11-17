<script setup lang="ts">
import { fileStatusText } from '../../../git/fileStatus'
import type { RepoFile } from '../../../types/api'

const props = defineProps<{ file: RepoFile; open: boolean; readOnly: boolean; disabled: boolean }>()
const emit = defineEmits<{ toggle: [trigger: HTMLElement]; editor: []; discard: []; stage: []; unstage: [] }>()

const name = () => props.file.path.slice(props.file.path.lastIndexOf('/') + 1)
const folder = () => (props.file.path.includes('/') ? props.file.path.slice(0, props.file.path.lastIndexOf('/')) : '')
const letter = () => (props.file.status === 'conflict' ? '!' : (props.file.kind ?? 'M'))
const LETTER_CLASS: Record<string, string> = { M: 'text-fg-muted', A: 'text-diff-add-fg', D: 'text-diff-del-fg', R: 'text-info-soft', '!': 'text-secondary' }
const STATUS_CLASS: Record<string, string> = {
  novo: 'text-diff-add-fg', apagado: 'text-diff-del-fg', renomeado: 'text-info-soft', 'em conflito': 'text-secondary',
  modificado: 'text-fg-subtle group-hover:text-fg-muted group-focus-within:text-fg-muted',
}
const iconButton = 'flex size-8 sm:size-6 items-center justify-center rounded text-fg-muted hover:bg-card hover:text-fg disabled:opacity-50'
</script>

<template>
  <div
    data-test="scm-file"
    :data-path="file.path"
    class="group flex h-8 min-w-0 sm:h-7 items-center gap-2 rounded pr-1 hover:bg-elevated focus-within:bg-elevated"
    :class="{ 'bg-card': open }"
  >
    <span data-test="file-letter" class="w-3 shrink-0 ml-1 text-center font-mono text-xs font-semibold" :class="LETTER_CLASS[letter()]" :title="file.status === 'conflict' ? 'Em conflito' : undefined">{{ letter() }}</span>
    <button type="button" data-test="file-open" aria-haspopup="dialog" :title="file.path" class="flex min-w-0 grow items-center gap-2 pl-1 text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary" @click="emit('toggle', $event.currentTarget as HTMLElement)">
      <span class="shrink-0 whitespace-nowrap text-[0.8125rem] text-fg">{{ name() }}</span>
      <span v-if="folder()" class="min-w-0 truncate font-mono text-[0.6875rem] text-fg-subtle">{{ folder() }}</span>
    </button>
    <span class="flex shrink-0 items-center opacity-100 sm:opacity-0 group-hover:opacity-100 group-focus-within:opacity-100">
      <button type="button" data-test="file-editor" :class="iconButton" aria-label="Abrir no editor" title="Abrir no editor" @click="emit('editor')">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 3h6v6" /><path d="M10 14 21 3" /><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /></svg>
      </button>
      <template v-if="!readOnly">
        <slot v-if="$slots.actions" name="actions" />
        <template v-else>
          <button type="button" data-test="file-discard" :class="iconButton" :disabled="disabled" aria-label="Descartar alterações" title="Descartar alterações" @click="emit('discard')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5" /></svg>
          </button>
          <button v-if="file.status === 'staged'" type="button" data-test="file-unstage" :class="iconButton" :disabled="disabled" aria-label="Tirar da preparação" title="Tirar da preparação" @click="emit('unstage')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><line x1="5" y1="12" x2="19" y2="12" /></svg>
          </button>
          <button v-else type="button" data-test="file-stage" :class="iconButton" :disabled="disabled" aria-label="Preparar" title="Preparar" @click="emit('stage')">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
          </button>
        </template>
      </template>
    </span>
    <span data-test="file-status" class="w-20 shrink-0 pr-1 text-right text-xs" :class="STATUS_CLASS[fileStatusText(file)]">{{ fileStatusText(file) }}</span>
  </div>
</template>
