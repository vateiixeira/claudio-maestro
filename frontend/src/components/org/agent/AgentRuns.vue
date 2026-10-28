<script setup lang="ts">
import { computed, onMounted, ref, useId, watch } from 'vue'
import { cancelAgentWakeup, errorMessage, listAgentWakeups } from '../../../api/http'
import { SOURCE_LABELS, formatRunDate } from '../../../org'
import { useOrgStore } from '../../../stores/org'
import { BTN_SMALL, ERROR } from '../styles'
import AgentRunRow from './AgentRunRow.vue'
import type { Wakeup } from '../../../types/org'

// The queue of requests waiting for the agent, and the history of its runs (the last 50, plus the ones in flight).
const props = defineProps<{ agentId: number }>()
const org = useOrgStore()

const PROBLEMS: ReadonlySet<string> = new Set(['failed', 'waiting', 'missed', 'skipped'])

const filter = ref<'all' | 'problems'>('all')
const wakeups = ref<Wakeup[]>([])
const error = ref<string | null>(null)
const cancelling = ref(new Set<number>())
const queueId = useId()
const historyId = useId()

const runs = computed(() => org.runsOf(props.agentId))
const visible = computed(() => (filter.value === 'all' ? runs.value : runs.value.filter((r) => PROBLEMS.has(r.outcome))))
const emptyText = computed(() => (runs.value.length > 0 ? 'Nenhum problema no histórico.' : 'Ainda não rodou.'))

async function loadRuns(): Promise<void> {
  try {
    await org.loadRuns(props.agentId)
  } catch (e) {
    error.value = errorMessage(e)
  }
}

async function loadWakeups(): Promise<void> {
  try {
    wakeups.value = await listAgentWakeups(props.agentId)
  } catch (e) {
    error.value = errorMessage(e)
  }
}

async function cancel(wakeupId: number): Promise<void> {
  if (cancelling.value.has(wakeupId)) return
  cancelling.value.add(wakeupId)
  error.value = null
  try {
    await cancelAgentWakeup(props.agentId, wakeupId)
    wakeups.value = wakeups.value.filter((w) => w.id !== wakeupId)
  } catch (e) {
    error.value = errorMessage(e)
    // It may have been served in the meantime.
    await loadWakeups()
  } finally {
    cancelling.value.delete(wakeupId)
  }
}

onMounted(() => { void loadRuns(); void loadWakeups() })
watch(() => org.changes[props.agentId], () => { void loadRuns(); void loadWakeups() })
// A request leaves the queue when a run takes it.
watch(() => `${runs.value.length}:${runs.value[0]?.id}:${runs.value[0]?.outcome}`, () => { void loadWakeups() })
</script>

<template>
  <div class="flex min-w-0 flex-col gap-6">
    <p v-if="error" data-test="runs-error" role="alert" :class="ERROR">{{ error }}</p>

    <section v-if="wakeups.length > 0" data-test="wakeups" :aria-labelledby="queueId" class="flex flex-col gap-2">
      <div>
        <h3 :id="queueId" class="m-0 text-base font-medium">Fila <span class="ml-1 rounded border border-line px-1.5 font-mono text-[0.6875rem] font-normal text-fg-subtle">{{ wakeups.length }}</span></h3>
        <p class="m-0 mt-0.5 text-xs text-fg-subtle">Pedidos que aguardam a vez do agente.</p>
      </div>
      <ul :aria-labelledby="queueId" class="m-0 flex list-none flex-col p-0">
        <li v-for="wakeup in wakeups" :key="wakeup.id" data-test="wakeup-row" class="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1 border-b border-line px-1 py-2.5 text-sm">
          <span class="w-24 shrink-0 text-fg-muted">{{ SOURCE_LABELS[wakeup.source] }}</span>
          <time class="shrink-0 font-mono text-xs text-fg-subtle" :datetime="new Date(wakeup.created_at * 1000).toISOString()">{{ formatRunDate(wakeup.created_at) }}</time>
          <span v-if="wakeup.text" class="min-w-0 flex-1 truncate text-xs text-fg-muted" :title="wakeup.text">{{ wakeup.text }}</span>
          <button type="button" data-test="wakeup-cancel" :class="[BTN_SMALL, 'ml-auto']" :disabled="cancelling.has(wakeup.id)" @click="cancel(wakeup.id)">{{ cancelling.has(wakeup.id) ? 'Cancelando…' : 'Cancelar' }}</button>
        </li>
      </ul>
    </section>

    <section :aria-labelledby="historyId" class="flex flex-col gap-2">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 :id="historyId" class="m-0 text-base font-medium">Execuções</h3>
          <p class="m-0 mt-0.5 text-xs text-fg-subtle">As últimas 50 e as que estão em andamento.</p>
        </div>
        <div role="group" aria-label="Filtrar execuções" class="flex shrink-0 gap-0.5 rounded-lg border border-line p-0.5">
          <button type="button" data-test="run-filter-all" :aria-pressed="filter === 'all'" class="h-7 cursor-pointer rounded-md border-0 bg-transparent px-2.5 text-xs text-fg-subtle focus-visible:outline-2 focus-visible:outline-primary aria-pressed:bg-card aria-pressed:text-fg" @click="filter = 'all'">Todas</button>
          <button type="button" data-test="run-filter-problems" :aria-pressed="filter === 'problems'" class="h-7 cursor-pointer rounded-md border-0 bg-transparent px-2.5 text-xs text-fg-subtle focus-visible:outline-2 focus-visible:outline-primary aria-pressed:bg-card aria-pressed:text-fg" @click="filter = 'problems'">Problemas</button>
        </div>
      </div>
      <p v-if="visible.length === 0" data-test="runs-empty" class="m-0 border-t border-line py-5 text-sm text-fg-subtle">{{ emptyText }}</p>
      <ul v-else :aria-labelledby="historyId" class="m-0 flex list-none flex-col p-0">
        <AgentRunRow v-for="run in visible" :key="run.id" :run="run" />
      </ul>
    </section>
  </div>
</template>
