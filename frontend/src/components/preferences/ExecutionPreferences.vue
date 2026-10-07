<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useUpdatesStore } from '../../stores/updates'
import { runModeLabel, SERVICE_UNINSTALL } from '../../updates/runMode'
import RunModeNotice from '../updates/RunModeNotice.vue'

const updates = useUpdatesStore()
const runMode = computed(() => updates.state?.run_mode ?? null)
const isService = computed(() => runMode.value?.kind.startsWith('service-') ?? false)
const loadFailed = ref(false)

async function load(): Promise<void> {
  loadFailed.value = false
  try {
    await updates.load()
  } catch {
    loadFailed.value = true
  }
}

// The page may open straight on Preferências, before anything loaded the updates.
onMounted(load)
</script>

<template>
  <section class="flex flex-col gap-7 px-7 py-6" aria-labelledby="execution-title">
    <h2 id="execution-title" class="m-0 text-base font-semibold">Execução</h2>
    <div v-if="runMode" class="flex flex-col gap-7">
      <div class="flex flex-col gap-2">
        <span class="font-mono text-xs tracking-[0.08em] text-fg-subtle uppercase">Como o Maestro está rodando</span>
        <p data-test="execution-mode" class="m-0 font-mono text-sm text-fg">{{ runModeLabel(runMode) }}</p>
      </div>
      <RunModeNotice :run-mode="runMode" :port="updates.state?.port" />
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
        class="h-11 cursor-pointer rounded-lg border border-line-strong px-4 font-medium text-fg hover:bg-card"
        @click="load"
      >
        Tentar de novo
      </button>
    </div>
    <p v-else class="m-0 text-sm text-fg-muted" role="status">Carregando…</p>
  </section>
</template>
