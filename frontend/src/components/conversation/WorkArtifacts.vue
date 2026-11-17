<script setup lang="ts">
import { computed } from 'vue'
import { formatRunningTime, formatTokens } from '../../format'
import { workArtifacts, type WorkAgent } from '../../conversation/workGroups'
import type { ToolItem } from '../../types/conversation'
import IconWorkKind from '../icons/IconWorkKind.vue'

// What a closed work block produced: the files it edited and the subagents it launched, as chips.
// A click asks the block to open on the action behind the chip.
const props = defineProps<{ items: ToolItem[]; sessionActive?: boolean }>()
const emit = defineEmits<{ open: [itemId: string] }>()

const artifacts = computed(() => workArtifacts(props.items, props.sessionActive ?? false))
const chip =
  'inline-flex min-h-8 max-w-full min-w-0 cursor-pointer items-center gap-2 rounded-[0.625rem] border border-line bg-panel px-2.5 text-[0.78rem] text-fg hover:bg-card focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary'

// The time and tokens of a finished subagent; nothing for one still running (its figures are not final).
function agentMeta(agent: WorkAgent): string {
  if (agent.status === 'running') return ''
  const parts: string[] = []
  if (agent.seconds != null && agent.seconds >= 1) parts.push(formatRunningTime(Math.round(agent.seconds)))
  if (agent.tokens != null && agent.tokens > 0) parts.push(`${formatTokens(agent.tokens)} tokens`)
  return parts.join(' · ')
}
const STATUS_WORD: Record<WorkAgent['status'], string> = { running: 'rodando', completed: 'concluído', failed: 'falhou', stopped: 'parado' }
</script>

<template>
  <div v-if="artifacts.files.length || artifacts.agents.length" data-test="work-artifacts" class="flex min-w-0 flex-wrap items-center gap-2">
    <button
      v-for="file in artifacts.files"
      :key="file.path"
      type="button"
      data-test="work-file-chip"
      :data-path="file.path"
      :title="file.path"
      :class="chip"
      @click="emit('open', file.itemId)"
    >
      <IconWorkKind kind="read" :size="13" class="text-type-file" />
      <span class="min-w-0 truncate font-mono text-info-soft">{{ file.name }}</span>
      <span v-if="file.added" class="shrink-0 font-mono text-xs text-diff-add-fg">+{{ file.added }}</span>
      <span v-if="file.removed" class="shrink-0 font-mono text-xs text-diff-del-fg">−{{ file.removed }}</span>
    </button>
    <button
      v-for="agent in artifacts.agents"
      :key="agent.itemId"
      type="button"
      data-test="work-agent-chip"
      :data-status="agent.status"
      :title="agent.description"
      :class="chip"
      @click="emit('open', agent.itemId)"
    >
      <IconWorkKind kind="agent" :size="13" class="text-type-agent" />
      <span class="min-w-0 truncate">{{ agent.description }}</span>
      <svg v-if="agent.status === 'completed'" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 text-primary" aria-hidden="true"><path d="M5 12.5 10 17 19 7" /></svg>
      <svg v-else-if="agent.status === 'failed'" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" aria-hidden="true" class="shrink-0 text-diff-del-fg"><path d="M6 6l12 12M18 6 6 18" /></svg>
      <svg v-else-if="agent.status === 'running'" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" class="shrink-0 animate-spin text-secondary-soft motion-reduce:animate-none" aria-hidden="true"><path d="M12 3a9 9 0 1 1-9 9" stroke-linecap="round" /></svg>
      <span class="sr-only">{{ STATUS_WORD[agent.status] }}</span>
      <span v-if="agentMeta(agent)" data-test="work-agent-meta" class="shrink-0 font-mono text-xs text-fg-muted">{{ agentMeta(agent) }}</span>
    </button>
  </div>
</template>
