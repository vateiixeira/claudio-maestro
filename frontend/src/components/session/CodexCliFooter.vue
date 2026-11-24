<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useMinuteClock } from '../../minuteClock'
import { useCodexCliStore } from '../../stores/codexCli'
import { formatReset, resetPhrase, severityClass } from '../sidebar/usageFormat'

const cli = useCodexCliStore()
const now = useMinuteClock()
const usage = computed(() => cli.info?.usage)
const account = computed(() => {
  const plan = usage.value?.plan
  if (plan) return /^chatgpt\b/i.test(plan) ? plan : `ChatGPT ${plan}`
  const auth = cli.info?.auth?.toLowerCase()
  if (auth === 'apikey') return 'Chave de API'
  if (auth?.startsWith('chatgpt')) return 'ChatGPT'
  return null
})

onMounted(() => { void cli.load() })
</script>

<template>
  <div data-test="codex-cli-footer" class="flex min-w-0 flex-col gap-1.5 px-1.5 py-1 text-xs">
    <div v-if="cli.info?.installed" class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-fg-muted">
      <span>Codex CLI <span v-if="cli.info.version" class="font-mono tabular-nums">{{ cli.info.version }}</span></span>
      <span v-if="account" data-test="codex-cli-plan" class="text-fg">{{ account }}</span>
    </div>
    <div
      v-for="limit in usage?.limits ?? []"
      :key="`${limit.kind}-${limit.label}`"
      class="flex min-w-0 items-center gap-2 text-fg-muted"
      :title="formatReset(limit.resets_at, now) ? `Renova ${resetPhrase(formatReset(limit.resets_at, now))}` : undefined"
    >
      <span>{{ limit.label }}</span>
      <span
        role="meter"
        aria-valuemin="0"
        aria-valuemax="100"
        :aria-valuenow="limit.percent"
        :aria-label="limit.label"
        class="h-1 min-w-8 grow overflow-hidden rounded-full bg-line"
      >
        <span class="block h-full rounded-full" :class="severityClass(limit.severity)" :style="{ width: `${limit.percent}%` }" />
      </span>
      <span class="shrink-0 text-right font-mono tabular-nums">{{ limit.percent }}%</span>
      <span v-if="limit.resets_at" class="shrink-0 font-mono text-fg-subtle">{{ formatReset(limit.resets_at, now) }}</span>
    </div>

    <p v-if="cli.loading && !cli.info" role="status" class="m-0 text-fg-subtle">Consultando o Codex CLI…</p>
    <p v-else-if="cli.info && !cli.info.installed" class="m-0 max-w-72 text-fg-muted">
      Instale o Codex CLI neste computador e execute <code>codex login</code> para conectar a conta.
    </p>
    <p v-else-if="cli.info?.requires_auth && !cli.info.auth" class="m-0 max-w-72 text-fg-muted">
      Execute <code>codex login</code> para conectar a conta e atualize o catálogo aqui.
    </p>
    <p v-if="usage?.error" class="m-0 max-w-72 text-fg-muted">Uso indisponível. {{ usage.error }}</p>
    <p v-if="cli.readError || (cli.info?.installed && cli.info.error && !cli.result)" role="status" class="m-0 max-w-72 text-diff-del-fg">
      {{ cli.readError ?? cli.info?.error }}
    </p>

    <div class="flex min-w-0 flex-wrap items-center gap-1">
      <button
        type="button"
        data-test="codex-cli-refresh"
        :aria-disabled="!!cli.busy"
        class="rounded-md px-1.5 py-1 text-left text-fg-muted hover:bg-elevated hover:text-fg focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-fg-muted aria-disabled:opacity-60"
        @click="cli.run('refresh')"
      >{{ cli.busy === 'refresh' ? 'Atualizando modelos…' : 'Atualizar modelos' }}</button>
      <button
        v-if="cli.info?.can_update"
        type="button"
        data-test="codex-cli-update"
        :aria-disabled="!!cli.busy"
        class="flex flex-wrap items-baseline gap-x-2 rounded-md px-1.5 py-1 text-left text-fg-muted hover:bg-elevated hover:text-fg focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-fg-muted aria-disabled:opacity-60"
        @click="cli.run('update')"
      >
        <span>{{ cli.busy === 'update' ? 'Atualizando Codex…' : 'Atualizar Codex' }}</span>
        <span v-if="cli.info.update_available && cli.info.latest" class="text-secondary">{{ cli.info.latest }} disponível</span>
      </button>
      <span v-else-if="cli.info?.update_available && cli.info.latest" class="px-1.5 py-1 text-fg-muted">
        {{ cli.info.latest }} disponível no gerenciador que instalou o Codex.
      </span>
    </div>
    <p
      v-if="cli.result"
      data-test="codex-cli-result"
      role="status"
      class="m-0 max-w-72"
      :class="cli.result.ok ? 'text-primary' : 'text-diff-del-fg'"
    >{{ cli.result.message }}</p>
  </div>
</template>
