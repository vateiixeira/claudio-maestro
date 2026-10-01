<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'

// Long outputs start as an 8-line preview; expanded, they still stop at `limit`
// lines until the user asks for everything.
const props = withDefaults(
  defineProps<{ text: string; limit?: number; preview?: number; variant?: 'default' | 'error'; flat?: boolean }>(),
  { limit: 200, preview: 8, variant: 'default' },
)

const expanded = ref(false)
const showAll = ref(false)
const lines = computed(() => props.text.split('\n'))
const hasMore = computed(() => lines.value.length > props.preview)
const previewing = computed(() => hasMore.value && !expanded.value)
const truncated = computed(() => expanded.value && !showAll.value && lines.value.length > props.limit)
const shown = computed(() => {
  if (previewing.value) return lines.value.slice(0, props.preview).join('\n')
  if (truncated.value) return lines.value.slice(0, props.limit).join('\n')
  return props.text
})

function collapse() {
  expanded.value = false
  showAll.value = false
}

const copyState = ref<'idle' | 'done' | 'failed'>('idle')
let copyTimer: ReturnType<typeof setTimeout> | null = null
async function copy() {
  try {
    await navigator.clipboard.writeText(props.text)
    copyState.value = 'done'
  } catch {
    copyState.value = 'failed'
  }
  if (copyTimer) clearTimeout(copyTimer)
  copyTimer = setTimeout(() => (copyState.value = 'idle'), 2000)
}
onBeforeUnmount(() => { if (copyTimer) clearTimeout(copyTimer) })

const statusText = computed(() => ({ idle: '', done: 'Copiado', failed: 'Não foi possível copiar' })[copyState.value])
const button = 'cursor-pointer rounded-md border border-line-strong bg-transparent px-2.5 py-1 text-xs text-fg-muted hover:bg-elevated hover:text-fg'
</script>

<template>
  <div>
    <div
      data-test="output-box"
      class="relative overflow-hidden rounded-md border"
      :class="variant === 'error' ? 'border-diff-del-fg/40 bg-diff-del-bg px-2.5 py-2 text-diff-del-fg' : flat ? 'border-transparent' : 'border-line bg-bg px-2.5 py-2'"
    >
      <pre class="m-0 font-mono text-xs leading-relaxed whitespace-pre-wrap break-words"><slot :text="shown">{{ shown }}</slot></pre>
      <div
        v-if="previewing"
        data-test="fade"
        aria-hidden="true"
        class="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-b from-transparent"
        :class="variant === 'error' ? 'to-diff-del-bg' : flat ? 'to-panel' : 'to-bg'"
      />
    </div>
    <div class="mt-2 flex flex-wrap items-center gap-2">
      <button v-if="previewing" type="button" data-test="show-lines" :class="button" @click="expanded = true">Ver as {{ lines.length }} linhas</button>
      <button v-if="truncated" type="button" data-test="show-all" :class="button" @click="showAll = true">
        Ver tudo ({{ lines.length }} linhas)
      </button>
      <button v-if="hasMore && expanded" type="button" data-test="collapse" :class="button" @click="collapse">Recolher</button>
      <button type="button" data-test="copy" :class="button" @click="copy">{{ copyState === 'done' ? 'Copiado' : 'Copiar' }}</button>
      <span v-if="copyState === 'failed'" aria-hidden="true" class="text-xs text-secondary-soft">Não foi possível copiar</span>
      <span role="status" class="sr-only">{{ statusText }}</span>
    </div>
  </div>
</template>
