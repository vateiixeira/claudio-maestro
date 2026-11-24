<script setup lang="ts">
import { computed, watch } from 'vue'
import { useMinuteClock } from '../../minuteClock'
import { useCodexCliStore } from '../../stores/codexCli'
import { useUsageStore } from '../../stores/usage'
import type { UsageLimit } from '../../types/api'
import { formatReset, resetPhrase, severityClass } from './usageFormat'

const props = withDefaults(defineProps<{ provider?: 'claude' | 'codex' }>(), { provider: 'claude' })
const claude = useUsageStore()
const codex = useCodexCliStore()
const now = useMinuteClock()
const isCodex = computed(() => props.provider === 'codex')
const usage = computed(() => isCodex.value ? codex.info?.usage : claude.snapshot)
const testPrefix = computed(() => isCodex.value ? 'codex-usage' : 'usage')

const error = computed(() => usage.value?.error ?? null)
const rows = computed(() => isCodex.value
  ? (usage.value?.limits ?? []).filter((limit) => limit.kind !== 'weekly_scoped')
  : [claude.session, claude.weekly].filter((limit): limit is UsageLimit => limit !== null))
// Before the first check the backend sends an empty snapshot: no frame until there is something to show.
const visible = computed(() => !!usage.value?.enabled && (rows.value.length > 0 || !!error.value || !!usage.value.plan))
const scoped = computed(() => isCodex.value ? (usage.value?.limits ?? []).filter((limit) => limit.kind === 'weekly_scoped') : claude.scoped)
const scopedLines = computed(() => scoped.value
  .map((limit) => `${limit.label.replace(/^Semana · /, '')}: ${limit.percent}%`))

watch([isCodex, now], ([active]) => {
  if (active) void codex.load(3 * 60 * 1000)
}, { immediate: true })

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
  <div v-if="visible" :data-test="`${testPrefix}-meter`" class="flex shrink-0 flex-col gap-1.5 border-t border-line px-4 py-2.5">
    <div
      v-if="usage?.plan || isCodex"
      :data-test="`${testPrefix}-plan`"
      class="flex min-w-0 items-center justify-between gap-2 text-xs"
      :class="{ 'opacity-60': error && !isCodex }"
      title="Plano da assinatura"
    >
      <span class="text-fg-subtle">{{ isCodex ? 'Codex' : 'Plano' }}</span>
      <span v-if="usage?.plan" class="truncate font-mono text-fg-muted">{{ usage.plan }}</span>
    </div>
    <p v-if="rows.length === 0 && error" :data-test="`${testPrefix}-unavailable`" class="m-0 text-xs text-fg-subtle" :title="error">Uso indisponível</p>
    <div
      v-for="limit in rows"
      :key="limit.kind"
      :data-test="`${testPrefix}-${limit.kind}`"
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
