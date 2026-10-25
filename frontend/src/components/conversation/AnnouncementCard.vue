<script setup lang="ts">
import { RouterLink } from 'vue-router'
import type { ParsedAnnouncement } from '../../conversation/announcements'
defineProps<{ announcement: ParsedAnnouncement }>()
</script>

<template>
  <article data-test="announcement-card" class="flex w-full items-start gap-2.5 rounded-lg border border-line bg-panel px-3.5 py-3 text-sm">
    <svg class="mt-0.5 shrink-0 text-fg-subtle" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" /></svg>
    <div class="min-w-0 grow">
      <time v-if="announcement.when" class="font-mono text-xs text-fg-subtle">{{ announcement.when }}</time>
      <p class="m-0 whitespace-pre-wrap break-words leading-relaxed text-fg-muted">{{ announcement.text }}</p>
      <RouterLink v-if="announcement.sessionId" :to="{ name: 'session', params: { id: announcement.sessionId } }" class="text-xs text-info-soft hover:text-fg focus-visible:outline-2 focus-visible:outline-primary">Abrir execução</RouterLink>
    </div>
  </article>
</template>
