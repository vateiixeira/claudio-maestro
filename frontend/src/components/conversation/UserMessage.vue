<script setup lang="ts">
import type { UserItem } from '../../types/conversation'

defineProps<{ item: UserItem }>()
</script>

<template>
  <div
    data-test="user-message"
    class="max-w-[85%] self-end whitespace-pre-wrap break-words rounded-[12px_12px_2px_12px] border border-line-strong bg-elevated px-3.5 py-2.5"
  >{{ item.text }}</div>
</template>
