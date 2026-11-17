<script setup lang="ts">
import type { SyncKind } from '../../git/repoLabel'

withDefaults(defineProps<{
  sync: { kind: SyncKind; ahead: number; behind: number }
  changes?: number
  error?: boolean
}>(), { changes: 0, error: false })
</script>

<template>
  <span class="inline-flex min-w-0 flex-wrap items-baseline gap-x-2.5 gap-y-0.5 text-xs">
    <span v-if="error" data-test="repo-state-error" class="inline-flex items-center gap-1 text-diff-del-fg">
      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M12 7v6m0 3v1" /></svg>erro
    </span>
    <span v-if="changes > 0 && !error" data-test="repo-changes" class="text-fg-muted" title="Soma das alterações preparadas, não preparadas e arquivos novos">{{ changes }} {{ changes === 1 ? 'alteração' : 'alterações' }}</span>
    <span data-test="sync-counts" class="inline-flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5" :role="!error && sync.kind === 'diverged' ? 'img' : undefined" :aria-label="!error && sync.kind === 'diverged' ? `${sync.behind} para baixar, ${sync.ahead} para subir` : undefined">
      <template v-if="!error">
        <span v-if="sync.kind === 'none'" data-test="sync-state" class="text-secondary-soft">sem upstream</span>
        <span v-else-if="sync.kind === 'unavailable'" data-test="sync-state" class="text-secondary-soft">sincronização indisponível</span>
        <span v-else-if="sync.kind === 'synced'" data-test="sync-state" class="text-fg-muted">em dia</span>
        <template v-else>
          <span v-if="sync.behind > 0" data-test="sync-behind" class="text-info-soft">{{ sync.behind }} para baixar</span>
          <span v-if="sync.ahead > 0" data-test="sync-ahead" class="text-secondary-soft">{{ sync.ahead }} para enviar</span>
        </template>
      </template>
    </span>
  </span>
</template>
