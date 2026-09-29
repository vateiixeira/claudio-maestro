<script setup lang="ts">
import { computed } from 'vue'
import { renderMarkdown } from '../../conversation/markdown'
import type { TextItem } from '../../types/conversation'

const props = defineProps<{ item: TextItem }>()

// Safe: markdown-it runs with `html: false`, so raw HTML in the text is escaped.
const html = computed(() => renderMarkdown(props.item.text))
</script>

<template>
  <div class="markdown">
    <div v-html="html" />
    <span
      v-if="item.streaming"
      data-test="streaming"
      class="ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-fg-muted align-text-bottom"
      aria-label="Escrevendo"
    />
  </div>
</template>
