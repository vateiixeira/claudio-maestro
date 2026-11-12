<script setup lang="ts">
import { computed, ref } from 'vue'
import { toolImageEntries } from '../../conversation/toolImages'
import type { ToolItem } from '../../types/conversation'
import ImageViewer from './ImageViewer.vue'
import ToolImageThumb from './ToolImageThumb.vue'

// Thumbnails of the images the given actions returned; a click opens the viewer, which walks through all of them.
const props = defineProps<{ items: readonly ToolItem[]; sessionActive?: boolean }>()

const entries = computed(() => toolImageEntries(props.items))
const viewing = ref<number | null>(null)
</script>

<template>
  <div v-if="entries.length" data-test="tool-image-strip" class="flex min-w-0 flex-col gap-1">
    <div v-if="entries.length > 1" data-test="tool-image-count" class="text-xs text-fg-subtle">{{ entries.length }} imagens</div>
    <div data-test="tool-image-list" class="flex min-w-0 gap-2 overflow-x-auto pb-1">
      <ToolImageThumb
        v-for="(entry, index) in entries"
        :key="`${entry.item.tool_use_id}:${entry.image.index}`"
        :entry="entry"
        :position="index + 1"
        :total="entries.length"
        :session-active="sessionActive"
        @open="viewing = index"
      />
    </div>
    <ImageViewer v-if="viewing !== null" :entries="entries" :start="viewing" :session-active="sessionActive" @close="viewing = null" />
  </div>
</template>
