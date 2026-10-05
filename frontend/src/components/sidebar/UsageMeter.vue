<script setup lang="ts">
import { computed } from 'vue'
import { useMinuteClock } from '../../minuteClock'
import { useUsageStore } from '../../stores/usage'
import type { UsageLimit } from '../../types/api'
import { formatReset, resetPhrase, severityClass } from './usageFormat'

const usage = useUsageStore()
const now = useMinuteClock()

const error = computed(() => usage.snapshot?.error ?? null)
const rows = computed(() => [usage.session, usage.weekly].filter((l): l is UsageLimit => l !== null))
// Before the first check the backend sends an empty snapshot: no frame until there is something to show.
const visible = computed(() => !!usage.snapshot?.enabled && (rows.value.length > 0 || !!error.value || !!usage.snapshot?.plan))
const scopedLines = computed(() => usage.scoped.map((l) => `${l.label.replace(/^Semana · /, '')}: ${l.percent}%`))

function reset(limit: UsageLimit): string {
  return formatReset(limit.resets_at, now.value)
}

function rowTitle(limit: UsageLimit): string {
  const lines: string[] = []
  const when = reset(limit)
  if (when) lines.push(`Renova ${resetPhrase(when)}`)
  if (limit.kind === 'weekly_all') lines.push(...scopedLines.value)
  if (error.value) lines.push(`Não atualizado: ${error.value}`)
  return lines.join('\n')
}

function ariaLabel(limit: UsageLimit): string {
  const when = reset(limit)
  return `${limit.label}: ${limit.percent}%` + (when ? `, renova ${resetPhrase(when)}` : '')
}
</script>

<template>
  <div v-if="visible" data-test="usage-meter" class="flex shrink-0 flex-col gap-1.5 border-t border-line px-4 py-2.5">
    <div
      v-if="usage.snapshot?.plan"
      data-test="usage-plan"
      class="flex min-w-0 items-center justify-between gap-2 text-xs"
      :class="{ 'opacity-60': error }"
      title="Plano da assinatura"
    >
      <span class="text-fg-subtle">Plano</span>
      <span class="truncate font-mono text-fg-muted">{{ usage.snapshot.plan }}</span>
    </div>
    <p v-if="rows.length === 0 && error" data-test="usage-unavailable" class="m-0 text-xs text-fg-subtle" :title="error">Uso indisponível</p>
    <div
      v-for="limit in rows"
      :key="limit.kind"
      :data-test="`usage-${limit.kind}`"
      class="flex min-w-0 items-center gap-2 text-xs"
      :class="{ 'opacity-60': error }"
      :title="rowTitle(limit)"
    >
      <span class="shrink-0 text-fg-subtle">{{ limit.label }}</span>
      <span
        role="meter"
        aria-valuemin="0"
        aria-valuemax="100"
        :aria-valuenow="limit.percent"
        :aria-label="ariaLabel(limit)"
        class="h-1 min-w-6 grow overflow-hidden rounded-full bg-line"
      >
        <span data-test="usage-fill" class="block h-full rounded-full" :class="severityClass(limit.severity)" :style="{ width: `${limit.percent}%` }" />
      </span>
      <span class="w-9 shrink-0 text-right font-mono text-fg-muted">{{ limit.percent }}%</span>
      <span class="shrink-0 font-mono text-fg-subtle">{{ reset(limit) }}</span>
    </div>
  </div>
</template>
