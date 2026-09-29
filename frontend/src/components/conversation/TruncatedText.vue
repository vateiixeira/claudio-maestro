<script setup lang="ts">
import { computed, ref } from 'vue'

const props = withDefaults(defineProps<{ text: string; limit?: number }>(), { limit: 200 })

const showAll = ref(false)
const lines = computed(() => props.text.split('\n'))
const truncated = computed(() => !showAll.value && lines.value.length > props.limit)
const shown = computed(() => (truncated.value ? lines.value.slice(0, props.limit).join('\n') : props.text))
</script>

<template>
  <div>
    <pre class="m-0 font-mono text-xs leading-relaxed whitespace-pre-wrap break-words"><slot :text="shown">{{ shown }}</slot></pre>
    <button
      v-if="truncated"
      type="button"
      data-test="show-all"
      class="mt-2 cursor-pointer rounded-md border border-line-strong bg-transparent px-2.5 py-1 text-xs text-primary-soft hover:bg-elevated"
      @click="showAll = true"
    >
      Ver tudo ({{ lines.length }} linhas)
    </button>
  </div>
</template>
