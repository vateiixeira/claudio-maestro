<script setup lang="ts">
import type { NoticeItem } from '../../types/conversation'

defineProps<{ item: NoticeItem }>()
</script>

<template>
  <div
    :data-level="item.level"
    :role="item.level === 'error' ? 'alert' : undefined"
    class="py-[3px] text-[0.84375rem] leading-[1.6] whitespace-pre-wrap [overflow-wrap:anywhere]"
    :class="{
      'text-fg-muted': item.level === 'info',
      'text-secondary-soft': item.level === 'warning',
      'text-diff-del-fg': item.level === 'error',
    }"
  >{{ item.text }}</div>
</template>
