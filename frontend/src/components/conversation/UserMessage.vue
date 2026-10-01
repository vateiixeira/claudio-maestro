<script setup lang="ts">
import { computed } from 'vue'
import { localImagesFor } from '../../conversation/localImages'
import type { Attachment, UserItem } from '../../types/conversation'

const props = defineProps<{ item: UserItem }>()
// Thumbnails exist only for images sent from this tab; the history keeps type and size.
const previews = computed(() => localImagesFor(props.item.id))

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
  <div data-test="user-message-card" class="flex w-full flex-col gap-2 rounded-lg border border-line-strong bg-card px-3.5 py-3">
    <div class="flex items-center gap-2">
      <span aria-hidden="true" class="flex size-[18px] items-center justify-center rounded-full bg-fg text-[10px] font-bold text-bg">V</span>
      <span class="cap text-fg">Você</span>
    </div>
    <div
      v-if="item.text"
      data-test="user-message"
      class="text-sm leading-[1.55] whitespace-pre-wrap break-words text-fg"
    >{{ item.text }}</div>
    <div v-if="previews?.length" class="flex flex-wrap gap-1.5">
      <img
        v-for="(url, index) in previews"
        :key="index"
        :src="url"
        :alt="`Imagem enviada ${index + 1}`"
        data-test="attachment-thumb"
        class="max-h-32 max-w-48 rounded-md border border-line-strong object-cover"
      />
    </div>
    <div v-if="item.images?.length && !previews?.length" class="flex flex-wrap gap-1">
      <span
        v-for="(attachment, index) in item.images"
        :key="index"
        data-test="attachment"
        class="rounded-md border border-line bg-panel px-2 py-0.5 font-mono text-xs text-fg-subtle"
      >{{ label(attachment) }}</span>
    </div>
  </div>
</template>
