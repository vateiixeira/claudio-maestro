<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import IconAlert from '../icons/IconAlert.vue'
import { useUpdatesStore } from '../../stores/updates'

const POLL_MS = 15_000

const updates = useUpdatesStore()
const open = computed(() => updates.agentdOpenSessions)
const busyText = computed(() =>
  open.value === 1
    ? '(1 sessão aberta; ela fecha sozinha quando ficar ociosa)'
    : `(${open.value} sessões abertas; elas fecham sozinhas quando ficam ociosas)`,
)

let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  timer = setInterval(() => {
    if (updates.showAgentdNotice) updates.load().catch(() => {})
  }, POLL_MS)
})
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
  <div
    v-if="updates.showAgentdNotice"
    data-test="agentd-notice"
    role="status"
    class="mx-2.5 mb-2 flex shrink-0 flex-col gap-2 rounded-lg border border-line bg-elevated px-3 py-2.5 text-xs leading-[1.5] text-fg-muted"
  >
    <p class="m-0 flex items-start gap-1.5">
      <IconAlert :size="13" class="mt-[3px] text-secondary" />
      <span>
        O agentd mudou nesta versão. Reinicie-o quando nenhuma sessão estiver rodando.
        <template v-if="updates.agentdBusy">{{ busyText }}</template>
      </span>
    </p>
    <div class="flex items-center gap-1.5">
      <button
        type="button"
        data-test="agentd-restart"
        class="h-7 cursor-pointer rounded-md border border-line-strong px-2.5 text-xs font-medium text-fg hover:bg-card disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
        :disabled="updates.agentdBusy || updates.agentdRestarting"
        @click="updates.restartAgentd()"
      >{{ updates.agentdRestarting ? 'Reiniciando…' : 'Reiniciar agentd' }}</button>
      <button
        type="button"
        data-test="agentd-dismiss"
        class="h-7 cursor-pointer rounded-md border border-line px-2.5 text-xs text-fg-muted hover:bg-card hover:text-fg"
        @click="updates.dismissAgentdNotice()"
      >Dispensar</button>
    </div>
    <p v-if="updates.agentdError" data-test="agentd-error" role="alert" class="m-0 text-diff-del-fg">{{ updates.agentdError }}</p>
  </div>
</template>
