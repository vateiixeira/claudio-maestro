<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useClaudeCliStore } from '../../stores/claudeCli'

const store = useClaudeCliStore()

onMounted(() => {
  store.clearResult()
  void store.load()
})

const versionText = computed(() => {
  const inUse = store.info?.in_use
  if (!inUse) return ''
  return inUse.source === 'bundled' ? `embutido · ${inUse.version}` : inUse.version
})

// Not `disabled`: a disabled button loses the focus, and Esc would stop closing the menu.
function onUpdate(): void {
  if (store.busy) return
  void store.update()
}
</script>

<template>
  <div data-test="claude-cli-footer" class="flex flex-col gap-1 py-0.5 text-xs">
    <template v-if="store.info">
      <p v-if="store.info.forced_bundled" data-test="claude-cli-forced" class="px-1.5 py-1 text-fg-subtle">Usando o Claude embutido (MAESTRO_CLAUDE_CLI).</p>
      <p v-else-if="!store.info.can_update" data-test="claude-cli-missing" class="max-w-64 px-1.5 py-1 text-fg-subtle">Instale o Claude no sistema para receber modelos novos sem esperar uma versão do Maestro.</p>
      <button
        v-else
        type="button"
        data-test="claude-cli-update"
        :aria-disabled="store.busy"
        class="flex items-center justify-between gap-3 rounded-md px-1.5 py-1 text-left text-fg-muted focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-fg-muted"
        :class="store.busy ? 'cursor-default' : 'cursor-pointer hover:bg-elevated hover:text-fg'"
        @click="onUpdate"
      >
        <template v-if="store.busy">Atualizando o Claude…</template>
        <template v-else>
          <span>Atualizar o Claude</span>
          <span class="text-fg-subtle">{{ versionText }}</span>
        </template>
      </button>
    </template>
    <p
      v-if="store.result"
      data-test="claude-cli-result"
      role="status"
      class="max-w-64 px-1.5 pb-1"
      :class="store.result.ok ? 'text-primary' : 'text-diff-del-fg'"
    >{{ store.result.message }}</p>
  </div>
</template>
