<script setup lang="ts">
import { computed, ref } from 'vue'
import { countLines, resultText, safeHttpUrl, str } from '../../conversation/tool'
import type { ToolItem } from '../../types/conversation'
import TruncatedText from './TruncatedText.vue'
import IconChevron from '../icons/IconChevron.vue'
import WorkHeader from './WorkHeader.vue'

// `headless`: inside a work block the row above is the header, so the card is just its body.
const props = defineProps<{ item: ToolItem; sessionActive?: boolean; headless?: boolean }>()
const open = ref(false)

const input = computed(() => props.item.input ?? {})
const subject = computed(() => str(input.value.pattern) || str(input.value.query) || str(input.value.url))
const path = computed(() => str(input.value.path))
const link = computed(() => (props.item.name === 'WebFetch' ? safeHttpUrl(str(input.value.url)) : null))
const output = computed(() => resultText(props.item.result?.content))
const isError = computed(() => props.item.result?.is_error === true)
const running = computed(() => props.item.streaming || (!props.item.result && !props.item.result_missing && props.sessionActive))
const status = computed<'ok' | 'running' | 'error' | 'idle'>(() => {
  if (running.value) return 'running'
  if (isError.value) return 'error'
  return props.item.result ? 'ok' : 'idle'
})
// The whole row is the toggle, unless it holds a link or has nothing to open.
const rowToggles = computed(() => !link.value && !!props.item.result)
const count = computed(() => {
  if (!props.item.result || isError.value || !['Grep', 'Glob'].includes(props.item.name)) return null
  const n = countLines(output.value)
  return `${n} ${n === 1 ? 'resultado' : 'resultados'}`
})
const meta = computed(() => {
  if (status.value === 'ok') return count.value ?? undefined
  return !props.item.result && !props.item.result_missing && !running.value ? 'sem resultado' : undefined
})
</script>

<template>
  <div :class="headless ? '[&>:first-child]:border-t-0' : ['overflow-hidden rounded-lg border bg-panel', isError ? 'border-diff-del-fg/40' : 'border-line']">
    <!-- A link cannot sit inside a button, so with one the row is plain and the chevron button toggles. -->
    <WorkHeader
      v-if="!headless"
      kind="search"
      :tag="item.name"
      :desc="subject"
      mono
      :as="rowToggles ? 'button' : 'div'"
      :open="rowToggles ? open : undefined"
      :aria-expanded="rowToggles ? open : undefined"
      :status="status"
      :meta="meta"
      @click="rowToggles && (open = !open)"
    >
      <template v-if="link" #desc>
        <a :href="link" target="_blank" rel="noopener noreferrer" class="text-info-soft underline">{{ link }}</a>
      </template>
      <template #trail>
        <span v-if="path" class="min-w-0 shrink truncate font-mono text-xs text-fg-subtle">em {{ path }}</span>
        <span v-if="item.result_missing" data-test="result-missing" class="shrink-0 text-xs text-fg-subtle">Resultado não disponível no histórico</span>
      </template>
      <template v-if="link && item.result" #actions>
        <button
          type="button"
          class="inline-flex shrink-0 cursor-pointer items-center border-none bg-transparent p-0 text-xs text-fg-subtle"
          :aria-expanded="open"
          :aria-label="open ? 'Recolher resultado' : 'Expandir resultado'"
          @click="open = !open"
        ><IconChevron :open="open" :size="12" /></button>
      </template>
    </WorkHeader>
    <p v-if="headless && link" class="m-0 truncate px-3 py-2 text-xs">
      <a :href="link" target="_blank" rel="noopener noreferrer" class="text-info-soft underline">{{ link }}</a>
    </p>
    <div v-if="(open || headless) && item.result" class="border-t border-line px-3 py-2" :class="isError ? 'text-diff-del-fg' : ''">
      <TruncatedText :text="output" />
    </div>
  </div>
</template>
