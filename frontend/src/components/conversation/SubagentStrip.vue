<script setup lang="ts">
import { computed, ref } from 'vue'
import { errorMessage, stopSubagents } from '../../api/http'
import { summarizeSubagents, type SubagentEntry } from '../../conversation/subagents'
import type { SubagentStatus } from '../../types/conversation'

// Strip above the message field while a subagent runs. Above this many, only a summary.
const LIST_LIMIT = 3

const props = defineProps<{ sessionId: string; entries: SubagentEntry[] }>()
const emit = defineEmits<{ select: [id: string] }>()

const STATUS_LABEL: Record<SubagentStatus, string> = {
  running: 'Rodando',
  completed: 'Concluído',
  failed: 'Com erro',
  stopped: 'Parado',
}

const collapsible = computed(() => props.entries.length > LIST_LIMIT)
const expanded = ref(false)
const showList = computed(() => !collapsible.value || expanded.value)
const summary = computed(() => summarizeSubagents(props.entries))
const runningCount = computed(() => props.entries.filter((e) => e.status === 'running').length)
const running = computed(() => runningCount.value > 0)

// Background subagents outlive the turn, so the composer's "Interromper" is not enough.
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
    aria-label="Subagentes"
    class="overflow-hidden rounded-lg border border-line bg-panel"
  >
    <button
      v-if="collapsible"
      type="button"
      data-test="subagent-summary"
      class="flex min-h-9 w-full cursor-pointer items-center gap-2 border-none bg-transparent px-3 text-left text-fg focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary"
      :aria-expanded="expanded"
      @click="expanded = !expanded"
    >
      <svg v-if="running" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" class="shrink-0 animate-spin text-primary" aria-hidden="true"><path d="M12 3a9 9 0 1 1-9 9" stroke-linecap="round" /></svg>
      <span class="cap shrink-0 text-fg-muted">Subagentes</span>
      <span class="min-w-0 grow truncate text-xs text-fg">{{ summary }}</span>
      <span aria-hidden="true" class="shrink-0 text-xs text-fg-muted">{{ expanded ? '▾' : '▸' }}</span>
    </button>
    <ul v-if="showList" class="m-0 flex max-h-40 list-none flex-col overflow-y-auto p-0" :class="collapsible ? 'border-t border-line' : ''">
      <li v-for="(entry, index) in entries" :key="entry.id" :class="index > 0 ? 'border-t border-line' : ''">
        <button
          type="button"
          data-test="subagent-row"
          class="flex min-h-9 w-full cursor-pointer flex-col justify-center gap-0.5 border-none bg-transparent px-3 py-1.5 text-left text-fg hover:bg-elevated focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary"
          :title="'Ir ao cartão do subagente'"
          @click="emit('select', entry.id)"
        >
          <span class="flex min-w-0 items-center gap-2">
            <span :data-status="entry.status" :aria-label="STATUS_LABEL[entry.status]" :title="STATUS_LABEL[entry.status]" role="img" class="flex shrink-0">
              <svg v-if="entry.status === 'running'" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" class="animate-spin text-primary" aria-hidden="true"><path d="M12 3a9 9 0 1 1-9 9" stroke-linecap="round" /></svg>
              <svg v-else-if="entry.status === 'completed'" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" class="text-primary" aria-hidden="true"><path d="M20 6 9 17l-5-5" /></svg>
              <svg v-else-if="entry.status === 'failed'" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" class="text-diff-del-fg" aria-hidden="true"><path d="M12 3 2 20h20L12 3z" /><line x1="12" y1="10" x2="12" y2="14" /></svg>
              <svg v-else width="13" height="13" viewBox="0 0 24 24" class="text-fg-muted" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="1.5" fill="currentColor" /></svg>
            </span>
            <span v-if="entry.kind" class="shrink-0 rounded bg-elevated px-1.5 py-px font-mono text-[11px] text-fg-muted">{{ entry.kind }}</span>
            <span class="min-w-0 grow truncate text-xs">{{ entry.description }}</span>
            <span class="shrink-0 text-[11px]" :class="entry.status === 'failed' ? 'text-diff-del-fg' : 'text-fg-muted'">{{ STATUS_LABEL[entry.status] }}</span>
          </span>
          <span v-if="entry.lastAction" data-test="subagent-last-action" class="block truncate pl-[21px] font-mono text-[11px] text-fg-muted">{{ entry.lastAction }}</span>
        </button>
      </li>
    </ul>
    <div
      v-if="running"
      class="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line px-3 py-1.5"
    >
      <button
        type="button"
        data-test="subagent-stop"
        class="flex min-h-8 cursor-pointer items-center gap-1.5 rounded-md border border-line-strong bg-elevated px-2.5 text-xs font-medium text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-default disabled:opacity-60"
        :disabled="stopping"
        @click="stopAll"
      >
        <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="2" /></svg>
        {{ runningCount === 1 ? 'Parar subagente' : 'Parar subagentes' }}
      </button>
      <p v-if="stopError" data-test="subagent-stop-error" role="alert" class="m-0 min-w-0 text-xs text-diff-del-fg">{{ stopError }}</p>
    </div>
  </div>
</template>
