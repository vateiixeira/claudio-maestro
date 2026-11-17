<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import IconCheck from '../icons/IconCheck.vue'
import IconCopy from '../icons/IconCopy.vue'

// The "Erro" band at the top of a failed action's body: its first line, and a button to copy all of it.
const props = defineProps<{ text: string }>()

const firstLine = computed(() => props.text.split('\n', 1)[0]!.trim())
const copied = ref(false)
let timer: ReturnType<typeof setTimeout> | null = null
async function copy() {
  try {
    await navigator.clipboard.writeText(props.text)
  } catch {
    // No clipboard permission: the full text is below, to copy by hand.
    return
  }
  copied.value = true
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => { copied.value = false }, 1500)
}
onBeforeUnmount(() => { if (timer) clearTimeout(timer) })
</script>

<template>
  <div data-test="work-error" class="flex items-center gap-3 bg-diff-del-bg py-1.5 pr-2 pl-3">
    <span class="cap text-diff-del-fg">Erro</span>
    <span data-test="work-error-text" class="min-w-0 grow truncate font-mono text-[0.78rem] text-diff-del-fg" :title="firstLine">{{ firstLine }}</span>
    <button
      type="button"
      data-test="work-error-copy"
      aria-label="Copiar erro"
      title="Copiar erro"
      class="flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-lg border-none bg-transparent text-diff-del-fg hover:bg-card focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
      @click="copy"
    >
      <IconCheck v-if="copied" :size="14" />
      <IconCopy v-else :size="14" />
    </button>
  </div>
</template>
