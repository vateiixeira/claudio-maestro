<script setup lang="ts">
// Opens a markdown file on the reader page, in a new tab.
defineProps<{ href: string }>()
</script>

<template>
  <a
    :href="href"
    target="_blank"
    rel="noopener noreferrer"
    data-test="md-view"
    title="Ler o arquivo numa aba nova"
    class="shrink-0 rounded-md border border-line-strong px-2 py-0.5 text-xs text-fg-muted no-underline hover:bg-elevated hover:text-fg focus-visible:outline-2 focus-visible:outline-primary"
  >Ver</a>
</template>
