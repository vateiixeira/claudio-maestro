<script setup lang="ts">
import { ref } from 'vue'
import type { TextItem } from '../../types/conversation'

defineProps<{ item: TextItem }>()
const open = ref(false)
</script>

<template>
  <div class="text-sm text-fg-muted">
    <button
      type="button"
      class="flex cursor-pointer items-center gap-1.5 border-none bg-transparent p-0 text-xs font-semibold text-fg-muted hover:text-fg"
      :aria-expanded="open"
      @click="open = !open"
    >
      <span aria-hidden="true">{{ open ? '▾' : '▸' }}</span>
      Raciocínio<span v-if="item.streaming" class="animate-pulse">…</span>
    </button>
    <p v-if="open" class="mt-2 mb-0 whitespace-pre-wrap border-l-2 border-line-strong pl-3 italic">{{ item.text }}</p>
  </div>
</template>
