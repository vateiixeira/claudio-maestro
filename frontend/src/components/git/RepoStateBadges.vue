<script setup lang="ts">
import IconArrowDown from '../icons/IconArrowDown.vue'
import IconArrowUp from '../icons/IconArrowUp.vue'
import type { SyncKind } from '../../git/repoLabel'

withDefaults(defineProps<{
  sync: { kind: SyncKind; ahead: number; behind: number }
  changes?: number
  error?: boolean
}>(), { changes: 0, error: false })
const chip = 'inline-flex min-h-5 items-center gap-1 rounded px-1.5 py-0.5 text-[0.6875rem] leading-none'
</script>

<template>
  <span class="inline-flex min-w-0 flex-wrap items-center gap-1.5">
    <span v-if="error" data-test="repo-state-error" :class="chip" class="bg-diff-del-bg text-diff-del-fg">
      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M12 7v6m0 3v1" /></svg>erro
    </span>
    <span v-if="changes > 0 && !error" data-test="repo-changes" :class="chip" class="bg-secondary/10 text-secondary-soft" title="Soma das alterações preparadas, não preparadas e arquivos novos">
      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M8 4h12v16H8zM4 8v12M11 9h6m-6 4h6" /></svg>{{ changes }} {{ changes === 1 ? 'alteração' : 'alterações' }}
    </span>
    <span data-test="sync-counts" class="inline-flex flex-wrap items-center gap-1.5" :role="!error && sync.kind === 'diverged' ? 'img' : undefined" :aria-label="!error && sync.kind === 'diverged' ? `${sync.behind} para baixar, ${sync.ahead} para subir` : undefined">
      <template v-if="!error">
        <span v-if="sync.kind === 'none'" :class="chip" class="bg-elevated text-fg-subtle"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 12h16" /></svg>sem upstream</span>
        <span v-else-if="sync.kind === 'unavailable'" :class="chip" class="bg-secondary/10 text-secondary-soft"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M12 7v6m0 3v1" /></svg>sincronização indisponível</span>
        <span v-else-if="sync.kind === 'synced'" :class="chip" class="bg-elevated text-fg-subtle"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="m5 12 4 4L19 6" /></svg>em dia</span>
        <template v-else>
          <span v-if="sync.behind > 0" :class="chip" class="bg-info/10 text-info-soft"><IconArrowDown :size="11" />{{ sync.behind }} para baixar</span>
          <span v-if="sync.ahead > 0" :class="chip" class="bg-primary/10 text-primary-soft"><IconArrowUp :size="11" />{{ sync.ahead }} para enviar</span>
        </template>
      </template>
    </span>
  </span>
</template>
