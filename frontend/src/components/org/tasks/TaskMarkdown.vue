<script setup lang="ts">
import { computed } from 'vue'
import { renderMarkdown } from '../../../conversation/markdown'

// Markdown of a description or a comment. Safe: markdown-it runs with `html: false`, so raw HTML is escaped.
const props = defineProps<{ text: string }>()
const html = computed(() => renderMarkdown(props.text))
</script>

<template>
  <div class="markdown max-w-[72ch] text-sm leading-relaxed"><div v-html="html" /></div>
</template>
