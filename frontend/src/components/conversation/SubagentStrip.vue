<script setup lang="ts">
import { computed, ref } from 'vue'
import { errorMessage, stopSubagents } from '../../api/http'
import { BACKGROUND_LABEL } from '../../conversation/background'
import { subagentClock, summarizeSubagents, type SubagentEntry } from '../../conversation/subagents'
import { useMinuteClock } from '../../minuteClock'
import type { SubagentStatus } from '../../types/conversation'
import IconChevron from '../icons/IconChevron.vue'
import ModelChip from './ModelChip.vue'

// Strip at the top of the composer's frame while a subagent or background command runs. Above this many, only a summary.
const LIST_LIMIT = 3

const props = defineProps<{ sessionId: string; entries: SubagentEntry[] }>()
const emit = defineEmits<{ select: [id: string] }>()

const STATUS_LABEL: Record<SubagentStatus, string> = {
  running: 'Rodando',
  completed: 'Concluído',
  failed: 'Com erro',
  stopped: 'Parado',
}

// A command's state reads like its card's ("Em background"); a subagent's like its own.
const stateLabel = (entry: SubagentEntry) => (entry.type === 'command' ? BACKGROUND_LABEL[entry.status] : STATUS_LABEL[entry.status])

const now = useMinuteClock()
const clockOf = (entry: SubagentEntry) => subagentClock(entry, now.value)

const hasCommands = computed(() => props.entries.some((e) => e.type === 'command'))
const regionLabel = computed(() => (hasCommands.value ? 'Tarefas em background' : 'Subagentes'))
const collapsible = computed(() => props.entries.length > LIST_LIMIT)
const expanded = ref(false)
const showList = computed(() => !collapsible.value || expanded.value)
const summary = computed(() => summarizeSubagents(props.entries))
const running = computed(() => props.entries.some((e) => e.status === 'running'))
// The bar names the latest of those running, with its clock.
const current = computed(() => [...props.entries].reverse().find((e) => e.status === 'running') ?? null)
const currentClock = computed(() => (current.value ? clockOf(current.value) : null))
// What "Parar" stops, named after what is running.
const stopLabel = computed(() => {
  const live = props.entries.filter((e) => e.status === 'running')
  const commands = live.filter((e) => e.type === 'command').length
  const one = live.length === 1
  if (commands === 0) return one ? 'Parar subagente' : 'Parar subagentes'
  if (commands === live.length) return one ? 'Parar comando' : 'Parar comandos'
  return 'Parar tarefas'
})

// Background subagents and commands outlive the turn, so the composer's "Interromper" is not enough.
const stopping = ref(false)
const stopError = ref<string | null>(null)
async function stopAll() {
  if (stopping.value) return
  stopping.value = true
  stopError.value = null
  try {
    await stopSubagents(props.sessionId)
  } catch (e) {
    stopError.value = errorMessage(e)
  } finally {
    stopping.value = false
  }
}
</script>

<template>
  <div
    v-if="entries.length > 0"
    data-test="subagent-strip"
    role="region"
    :aria-label="regionLabel"
  >
    <div data-test="subagent-bar" class="flex min-h-11 flex-wrap items-center gap-x-2.5 gap-y-1 border-b border-line py-1 pr-2 pl-3.5">
      <svg v-if="running" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" class="shrink-0 animate-spin text-secondary" aria-hidden="true"><path d="M12 3a9 9 0 1 1-9 9" stroke-linecap="round" /></svg>
      <span class="cap shrink-0 text-fg-subtle">{{ regionLabel }}</span>
      <span data-test="subagent-counts" class="shrink-0 text-[0.8125rem] text-fg">{{ summary }}</span>
      <span v-if="current" data-test="subagent-current" class="ml-auto flex min-w-0 items-center gap-2">
        <span class="min-w-0 truncate text-xs text-fg-muted">{{ current.description }}</span>
        <span v-if="currentClock" class="shrink-0 font-mono text-[0.6875rem] tabular-nums" :class="currentClock.stale ? 'text-secondary-soft' : 'text-fg-subtle'">{{ currentClock.text }}</span>
      </span>
      <span v-else class="grow" />
      <button
        v-if="running"
        type="button"
        data-test="subagent-stop"
        class="flex min-h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-md border border-line-strong bg-elevated px-2.5 text-xs font-medium text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-default disabled:opacity-60"
        :disabled="stopping"
        @click="stopAll"
      >
        <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="2" /></svg>
        {{ stopLabel }}
      </button>
      <button
        v-if="collapsible"
        type="button"
        data-test="subagent-summary"
        class="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-md border-none bg-transparent text-fg-muted hover:bg-elevated hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
        :aria-label="expanded ? 'Recolher a lista de subagentes' : 'Ver todos os subagentes'"
        :aria-expanded="expanded"
        @click="expanded = !expanded"
      >
        <IconChevron :open="expanded" :size="14" />
      </button>
    </div>
    <p v-if="stopError" data-test="subagent-stop-error" role="alert" class="m-0 border-b border-line px-3.5 py-1.5 text-xs text-diff-del-fg">{{ stopError }}</p>
    <ul v-if="showList" class="m-0 flex max-h-40 list-none flex-col overflow-y-auto border-b border-line p-0">
      <li v-for="(entry, index) in entries" :key="entry.id" :class="index > 0 ? 'border-t border-line' : ''">
        <button
          type="button"
          data-test="subagent-row"
          class="flex min-h-9 w-full cursor-pointer flex-col justify-center gap-0.5 border-none bg-transparent px-3 py-1.5 text-left text-fg hover:bg-elevated focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary"
          :title="entry.type === 'command' ? 'Ir ao cartão do comando' : 'Ir ao cartão do subagente'"
          @click="emit('select', entry.id)"
        >
          <span class="flex min-w-0 items-center gap-2">
            <span :data-status="entry.status" :aria-label="stateLabel(entry)" :title="stateLabel(entry)" role="img" class="flex shrink-0">
              <svg v-if="entry.status === 'running'" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" class="animate-spin text-secondary" aria-hidden="true"><path d="M12 3a9 9 0 1 1-9 9" stroke-linecap="round" /></svg>
              <svg v-else-if="entry.status === 'completed'" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" class="text-primary" aria-hidden="true"><path d="M20 6 9 17l-5-5" /></svg>
              <svg v-else-if="entry.status === 'failed'" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" class="text-diff-del-fg" aria-hidden="true"><path d="M12 3 2 20h20L12 3z" /><line x1="12" y1="10" x2="12" y2="14" /></svg>
              <svg v-else width="13" height="13" viewBox="0 0 24 24" class="text-fg-subtle" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="1.5" fill="currentColor" /></svg>
            </span>
            <span v-if="entry.kind" data-test="subagent-kind" :title="entry.kind" class="min-w-0 max-w-[10rem] truncate rounded-full bg-elevated px-2 py-px font-mono text-[0.6875rem] text-fg-muted">{{ entry.kind }}</span>
            <ModelChip v-if="entry.type === 'agent'" :model="entry.model" />
            <span data-test="subagent-desc" class="min-w-0 grow basis-0 truncate text-xs">{{ entry.description }}</span>
            <span
              v-if="clockOf(entry)"
              data-test="subagent-time"
              class="shrink-0 font-mono text-[0.6875rem] tabular-nums"
              :class="clockOf(entry)!.stale ? 'text-secondary-soft' : 'text-fg-subtle'"
              :title="clockOf(entry)!.stale ? 'Sem atividade há algum tempo' : undefined"
            >{{ clockOf(entry)!.text }}</span>
            <span data-test="subagent-state" class="shrink-0 text-[0.6875rem]" :class="entry.status === 'failed' ? 'text-diff-del-fg' : entry.status === 'running' ? 'text-secondary-soft' : 'text-fg-subtle'">{{ stateLabel(entry) }}</span>
          </span>
          <span v-if="entry.lastAction" data-test="subagent-last-action" class="block truncate pl-[21px] font-mono text-[0.6875rem] text-fg-subtle">{{ entry.lastAction }}</span>
        </button>
      </li>
    </ul>
  </div>
</template>
