<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useEventSocket } from '../../api/socket'
import { useUpdatesStore } from '../../stores/updates'
import { runModeLabel, runModeNotice, SERVICE_UNINSTALL, serviceInstallCommand } from '../../updates/runMode'

const updates = useUpdatesStore()
const socket = useEventSocket()
const runMode = computed(() => updates.state?.run_mode ?? null)
const isService = computed(() => runMode.value?.kind.startsWith('service-') ?? false)
const notice = computed(() => (runMode.value ? runModeNotice(runMode.value) : null))
const installCommand = computed(() => serviceInstallCommand(updates.state?.port))
const connectionText = computed(() => {
  switch (socket.status.value) {
    case 'connected': return 'Conectado'
    case 'reconnecting': return 'Sem conexão com o servidor. Reconectando…'
    default: return 'Conectando…'
  }
})
// runModeLabel joins "label: unit" for a custom service; split them using the unit the backend reports.
const modeParts = computed(() => {
  const info = runMode.value
  if (!info) return { label: '', unit: null as string | null }
  const label = runModeLabel(info)
  const suffix = info.unit ? `: ${info.unit}` : null
  if (suffix && label.endsWith(suffix)) return { label: label.slice(0, -suffix.length), unit: info.unit }
  return { label, unit: null }
})
const dotClass = computed(() => {
  switch (socket.status.value) {
    case 'connected': return 'bg-primary'
    case 'reconnecting': return 'bg-secondary'
    default: return 'bg-fg-subtle'
  }
})
const loadFailed = ref(false)
const copied = ref(false)
let copiedTimer: ReturnType<typeof setTimeout> | undefined
onBeforeUnmount(() => clearTimeout(copiedTimer))

async function load(): Promise<void> {
  loadFailed.value = false
  try {
    await updates.load()
  } catch {
    loadFailed.value = true
  }
}

async function copy(): Promise<void> {
  try {
    await navigator.clipboard.writeText(installCommand.value)
    copied.value = true
    clearTimeout(copiedTimer)
    copiedTimer = setTimeout(() => (copied.value = false), 1500)
  } catch {
    // No clipboard permission: the command stays visible to copy by hand.
  }
}

// The page may open straight on Preferências, before anything loaded the updates.
onMounted(load)
</script>

<template>
  <section class="flex flex-col gap-7 px-7 py-6" aria-labelledby="execution-title">
    <h2 id="execution-title" class="m-0 text-base font-semibold">Execução</h2>
    <div v-if="runMode" class="flex flex-col gap-6">
      <dl class="m-0">
        <div class="grid min-h-11 items-center gap-x-4 border-b border-line py-2 text-sm sm:grid-cols-[14rem_minmax(0,1fr)]">
          <dt class="text-fg-muted">Como o Maestro está rodando</dt>
          <dd data-test="execution-mode" class="m-0 flex min-w-0 flex-wrap items-center gap-x-2 text-fg">
            <span>{{ modeParts.label }}</span>
            <span v-if="modeParts.unit" data-test="execution-unit" class="font-mono text-xs break-all text-fg-muted">{{ modeParts.unit }}</span>
          </dd>
        </div>
        <div class="grid min-h-11 items-center gap-x-4 border-b border-line py-2 text-sm sm:grid-cols-[14rem_minmax(0,1fr)]">
          <dt class="text-fg-muted">Conexão com o servidor</dt>
          <dd data-test="execution-connection" class="m-0 flex min-w-0 items-center gap-2 text-fg">
            <span :class="['size-2 shrink-0 rounded-full', dotClass]" aria-hidden="true" />
            <span role="status">{{ connectionText }}</span>
          </dd>
        </div>
        <div class="grid min-h-11 items-center gap-x-4 border-b border-line py-2 text-sm sm:grid-cols-[14rem_minmax(0,1fr)]">
          <dt class="text-fg-muted">Versão</dt>
          <dd data-test="execution-version" class="m-0 min-w-0 font-mono text-fg">{{ updates.state ? `v${updates.state.current}` : '' }}</dd>
        </div>
      </dl>
      <div v-if="notice" data-test="run-mode-notice" class="flex flex-col gap-2.5 rounded-xl bg-card px-4 py-3.5">
        <p class="m-0 text-sm leading-relaxed text-fg-muted">{{ notice }}</p>
        <div class="flex items-center gap-2.5 rounded-lg border border-line bg-bg py-2 pr-2 pl-3">
          <code data-test="run-mode-command" class="min-w-0 grow overflow-x-auto font-mono text-xs text-fg">{{ installCommand }}</code>
          <button
            type="button"
            data-test="execution-copy"
            class="flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-md border border-line px-3 text-xs text-fg-muted hover:bg-elevated hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg-muted"
            @click="copy"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <rect x="9" y="9" width="11" height="11" rx="2" />
              <path d="M5 15V6a2 2 0 0 1 2-2h9" />
            </svg>
            {{ copied ? 'Copiado' : 'Copiar' }}
          </button>
        </div>
      </div>
      <div v-if="isService" class="flex flex-col gap-2">
        <span class="text-xs text-fg-muted">Para remover o serviço:</span>
        <code data-test="execution-uninstall" class="w-fit max-w-full overflow-x-auto rounded-md border border-line bg-elevated px-2.5 py-1.5 font-mono text-xs text-fg">{{ SERVICE_UNINSTALL }}</code>
      </div>
    </div>
    <div v-else-if="loadFailed" class="flex flex-col items-start gap-3">
      <p role="alert" class="m-0 w-full rounded-lg border border-diff-del-fg/40 bg-diff-del-bg px-3.5 py-2.5 text-sm text-diff-del-fg">
        Não foi possível ler como o Maestro está rodando.
      </p>
      <button
        type="button"
        data-test="execution-retry"
        class="h-11 cursor-pointer rounded-lg border border-line-strong px-4 font-medium text-fg hover:bg-card focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg-muted"
        @click="load"
      >
        Tentar de novo
      </button>
    </div>
    <p v-else class="m-0 text-sm text-fg-muted" role="status">Carregando…</p>
  </section>
</template>
