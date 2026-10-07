<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import type { RunModeInfo } from '../../types/api'
import { runModeNotice, SERVICE_INSTALL } from '../../updates/runMode'

const props = defineProps<{ runMode: RunModeInfo }>()
const text = computed(() => runModeNotice(props.runMode))
const copied = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined
onBeforeUnmount(() => clearTimeout(timer))

async function copy(): Promise<void> {
  try {
    await navigator.clipboard.writeText(SERVICE_INSTALL)
    copied.value = true
    clearTimeout(timer)
    timer = setTimeout(() => (copied.value = false), 1500)
  } catch {
    // No clipboard permission: the command stays visible to copy by hand.
  }
}
</script>

<template>
  <div v-if="text" data-test="run-mode-notice" class="flex flex-col gap-2 rounded-lg border border-line bg-elevated px-3.5 py-3 text-xs leading-[1.5] text-fg-muted">
    <p class="m-0">{{ text }}</p>
    <div class="flex items-center gap-2">
      <code data-test="run-mode-command" class="min-w-0 grow overflow-x-auto font-mono text-fg">{{ SERVICE_INSTALL }}</code>
      <button type="button" data-test="run-mode-copy" class="h-7 shrink-0 cursor-pointer rounded-md border border-line px-2 text-xs text-fg-muted hover:bg-card hover:text-fg" @click="copy">
        {{ copied ? 'Copiado' : 'Copiar' }}
      </button>
    </div>
  </div>
</template>
