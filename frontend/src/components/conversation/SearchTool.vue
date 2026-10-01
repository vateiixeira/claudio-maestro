<script setup lang="ts">
import { computed, ref } from 'vue'
import { countLines, resultText, safeHttpUrl, str } from '../../conversation/tool'
import type { ToolItem } from '../../types/conversation'
import TruncatedText from './TruncatedText.vue'
import IconChevron from '../icons/IconChevron.vue'

const props = defineProps<{ item: ToolItem; sessionActive?: boolean }>()
const open = ref(false)

const input = computed(() => props.item.input ?? {})
const subject = computed(() => str(input.value.pattern) || str(input.value.query) || str(input.value.url))
const path = computed(() => str(input.value.path))
const link = computed(() => (props.item.name === 'WebFetch' ? safeHttpUrl(str(input.value.url)) : null))
const output = computed(() => resultText(props.item.result?.content))
const isError = computed(() => props.item.result?.is_error === true)
const running = computed(() => props.item.streaming || (!props.item.result && !props.item.result_missing && props.sessionActive))
const count = computed(() => {
  if (!props.item.result || isError.value || !['Grep', 'Glob'].includes(props.item.name)) return null
  const n = countLines(output.value)
  return `${n} ${n === 1 ? 'resultado' : 'resultados'}`
})
</script>

<template>
  <div class="overflow-hidden rounded-lg border bg-panel" :class="isError ? 'border-diff-del-fg/40' : 'border-line'">
    <div class="flex items-center gap-2 px-3 py-2">
      <button
        v-if="item.result"
        type="button"
        class="inline-flex cursor-pointer items-center border-none bg-transparent p-0 text-xs text-fg-subtle"
        :aria-expanded="open"
        :aria-label="open ? 'Recolher resultado' : 'Expandir resultado'"
        @click="open = !open"
      ><IconChevron :open="open" :size="12" /></button>
      <span class="cap text-fg">{{ item.name }}</span>
      <a
        v-if="link"
        :href="link"
        target="_blank"
        rel="noopener noreferrer"
        class="min-w-0 grow truncate font-mono text-xs text-info-soft underline"
      >{{ link }}</a>
      <span v-else class="min-w-0 grow truncate font-mono text-xs text-fg">{{ subject }}</span>
      <span v-if="path" class="truncate font-mono text-xs text-fg-subtle">em {{ path }}</span>
      <span v-if="item.result_missing" data-test="result-missing" class="text-xs text-fg-subtle">Resultado não disponível no histórico</span>
      <span v-else-if="running" class="animate-pulse text-xs text-primary-soft">rodando…</span>
      <span v-else-if="isError" class="text-xs text-diff-del-fg">erro</span>
      <span v-else-if="count" class="text-xs text-fg-subtle">{{ count }}</span>
      <span v-else-if="!item.result" class="text-xs text-fg-subtle">sem resultado</span>
    </div>
    <div v-if="open && item.result" class="border-t border-line px-3 py-2" :class="isError ? 'text-diff-del-fg' : ''">
      <TruncatedText :text="output" />
    </div>
  </div>
</template>
