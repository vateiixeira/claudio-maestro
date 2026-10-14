<script setup lang="ts">
import ConfirmDialog from '../../ConfirmDialog.vue'
import type { Confirmation } from '../../../git/confirmation'

defineProps<{ confirmation: Confirmation }>()
const emit = defineEmits<{ confirm: []; cancel: [] }>()
const folder = (path: string) => (path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '')
const base = (path: string) => path.slice(path.lastIndexOf('/') + 1)
</script>

<template>
  <ConfirmDialog :title="confirmation.title" :confirm-label="confirmation.confirmLabel" :tone="confirmation.tone" @confirm="emit('confirm')" @cancel="emit('cancel')">
    <div v-if="confirmation.running" data-test="confirm-running" class="flex items-start gap-2.5 rounded-lg border border-line bg-surface px-3 py-2.5 text-[0.8125rem] leading-normal">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true" class="mt-0.5 shrink-0 text-primary motion-safe:animate-spin"><path d="M21 12a9 9 0 1 1-6.22-8.56" /></svg>
      <span><span class="font-medium">{{ confirmation.running.title }}</span> <span class="text-fg-muted">está em execução em {{ confirmation.repoName }}.</span></span>
    </div>
    <div v-if="confirmation.file" class="flex items-center gap-2.5 rounded-md border border-line bg-bg px-3 py-2">
      <span class="font-mono text-xs font-semibold">{{ confirmation.file.kind }}</span>
      <span class="min-w-0 truncate"><span class="text-[0.8125rem]">{{ base(confirmation.file.path) }}</span><span class="ml-2 font-mono text-xs text-fg-subtle">{{ folder(confirmation.file.path) }}</span></span>
      <span class="ml-auto font-mono text-xs"><span v-if="confirmation.file.added != null" class="text-diff-add-fg">+{{ confirmation.file.added }}</span> <span v-if="confirmation.file.removed != null" class="text-diff-del-fg">−{{ confirmation.file.removed }}</span></span>
    </div>
    <p v-for="(line, index) in confirmation.lines" :key="index" class="m-0 text-sm leading-relaxed text-fg-muted" :class="{ 'text-xs text-fg-subtle': line.startsWith('Num arquivo novo') }">{{ line }}</p>
  </ConfirmDialog>
</template>
