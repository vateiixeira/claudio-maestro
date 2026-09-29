<script setup lang="ts">
import type { NoticeItem } from '../../types/conversation'

defineProps<{ item: NoticeItem }>()
</script>

<template>
  <div
    :data-level="item.level"
    :role="item.level === 'error' ? 'alert' : undefined"
    class="rounded-md border px-3 py-2 text-sm whitespace-pre-wrap"
    :class="{
      'border-line bg-panel text-fg-muted': item.level === 'info',
      'border-secondary/50 bg-secondary/10 text-secondary-soft': item.level === 'warning',
      'border-diff-del-fg/40 bg-diff-del-bg text-diff-del-fg': item.level === 'error',
    }"
  >{{ item.text }}</div>
</template>
