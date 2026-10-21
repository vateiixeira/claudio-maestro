<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import { MESSAGE_FOCUS_KEY } from '../../conversation/find'
import { localImagesFor } from '../../conversation/localImages'
import type { Attachment, UserItem } from '../../types/conversation'
import BashPane from './BashPane.vue'
import TerminalRunBox from './TerminalRunBox.vue'
import WorkHeader from './WorkHeader.vue'

const props = defineProps<{ item: UserItem }>()
// Thumbnails exist only for images sent from this tab; the history keeps type and size.
const previews = computed(() => localImagesFor(props.item.id))
// The search took the user here: the message is marked for a moment.
const focus = inject(MESSAGE_FOCUS_KEY, ref<string | null>(null))
const highlighted = computed(() => focus.value === props.item.id)

function subtype(mediaType: string | null): string {
  return (mediaType ?? '').split('/')[1]?.split('+')[0] ?? ''
}

function size(bytes: number | null): string {
  if (bytes == null) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} MB`
}

/** "Imagem · png · 120 KB" or "Documento PDF". */
function label(attachment: Attachment): string {
  const kind = subtype(attachment.media_type)
  if (attachment.type === 'document') return kind ? `Documento ${kind.toUpperCase()}` : 'Documento'
  return ['Imagem', kind, size(attachment.size)].filter(Boolean).join(' · ')
}
</script>

<template>
  <!-- Output of a command run in the terminal: like Claude's own actions, on the left and without the bubble. -->
  <TerminalRunBox
    v-if="item.terminal_run"
    :run="item.terminal_run"
    :data-item-id="item.id"
    :data-highlighted="highlighted ? 'true' : undefined"
    tabindex="-1"
    class="w-full"
    :class="highlighted ? 'ring-2 ring-primary' : ''"
  />
  <!-- Like a messenger: what the user sends sits on the right, the model's replies on the left. -->
  <div v-else data-test="user-message-row" class="flex w-full justify-end pl-10">
    <div
      data-test="user-message-card"
      :data-item-id="item.id"
      tabindex="-1"
      :data-highlighted="highlighted ? 'true' : undefined"
      class="flex max-w-[72ch] min-w-0 flex-col items-end gap-2 rounded-2xl rounded-br-md border border-primary/25 bg-primary-tint px-3.5 py-2.5 outline-none"
      :class="highlighted ? 'ring-2 ring-primary' : ''"
    >
      <span class="sr-only">Você:</span>
      <div
        v-for="(snippet, index) in item.terminal_snippets"
        :key="index"
        data-test="terminal-snippet"
        class="min-w-0 self-stretch overflow-hidden rounded-lg border border-line bg-panel text-left"
      >
        <WorkHeader kind="bash" label="Trecho do terminal" desc="" status="idle" class="[&_.cap]:w-auto" />
        <BashPane label="OUT" name="Trecho do terminal" copy-label="Copiar trecho" :text="snippet" :preview="4" class="border-t border-line" />
      </div>
      <div
        v-if="item.text"
        data-test="user-message"
        class="self-stretch text-sm leading-[1.55] whitespace-pre-wrap break-words text-fg"
      >{{ item.text }}</div>
      <div v-if="previews?.length" class="flex flex-wrap justify-end gap-1.5">
        <img
          v-for="(url, index) in previews"
          :key="index"
          :src="url"
          :alt="`Imagem enviada ${index + 1}`"
          data-test="attachment-thumb"
          class="max-h-32 max-w-48 rounded-lg border border-primary/25 object-cover"
        />
      </div>
      <div v-if="item.images?.length && !previews?.length" class="flex flex-wrap justify-end gap-1">
        <span
          v-for="(attachment, index) in item.images"
          :key="index"
          data-test="attachment"
          class="rounded-md border border-primary/25 bg-surface/50 px-2 py-0.5 font-mono text-xs text-fg-muted"
        >{{ label(attachment) }}</span>
      </div>
      <span
        v-if="item.remote"
        data-test="remote-mark"
        title="Enviada pelo Remote Control"
        class="text-xs text-fg-subtle"
      >via Remote Control</span>
    </div>
  </div>
</template>
