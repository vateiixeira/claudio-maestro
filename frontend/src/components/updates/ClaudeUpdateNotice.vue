<script setup lang="ts">
import { computed, onBeforeUnmount, watch } from 'vue'
import { useClaudeCliStore } from '../../stores/claudeCli'

/** How long the outcome of the update stays in the sidebar footer. */
const RESULT_MS = 8000

const store = useClaudeCliStore()

const latest = computed(() => store.info?.latest?.version ?? '')
const installed = computed(() => store.info?.system?.version ?? store.info?.in_use.version ?? '')
const label = computed(() => `Claude ${latest.value} disponível. Você está na ${installed.value}. Clique para atualizar.`)
const available = computed(() => !!store.info?.update_available && !!latest.value)
const visible = computed(() => store.busy || !!store.result || available.value)

let timer: ReturnType<typeof setTimeout> | undefined
function stopTimer(): void {
  clearTimeout(timer)
  timer = undefined
}
watch(
  () => store.result,
  (result) => {
    stopTimer()
    if (result) timer = setTimeout(() => store.clearResult(), RESULT_MS)
  },
  { immediate: true },
)
onBeforeUnmount(stopTimer)

// Not `disabled`: a disabled button loses the focus.
function onUpdate(): void {
  if (store.busy) return
  void store.update()
}

const showButton = computed(() => store.busy || (!store.result && available.value))
</script>

<template>
  <div v-if="visible" class="flex min-w-0 shrink-0 items-center px-4 pb-2 font-mono text-xs text-fg-subtle">
    <button
      v-if="showButton"
      type="button"
      data-test="claude-update-notice"
      :aria-disabled="store.busy"
      :aria-label="store.busy ? undefined : label"
      :title="store.busy ? undefined : label"
      class="min-w-0 truncate rounded-sm border-none bg-transparent p-0 text-left font-mono text-xs text-fg-subtle focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg-muted"
      :class="store.busy ? 'cursor-default' : 'cursor-pointer hover:text-fg'"
      @click="onUpdate"
    >
      <template v-if="store.busy">Atualizando o Claude…</template>
      <template v-else>Claude {{ installed }} <span class="text-secondary">· {{ latest }} disponível</span></template>
    </button>
    <p
      v-else-if="store.result"
      data-test="claude-update-result"
      role="status"
      class="min-w-0 break-words"
      :class="store.result.ok ? 'text-primary' : 'text-diff-del-fg'"
    >{{ store.result.message }}</p>
  </div>
</template>
