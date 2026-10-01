<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { agentStatus, SUBAGENT_FOCUS_KEY } from '../../conversation/subagents'
import { str } from '../../conversation/tool'
import type { SubagentStatus, ToolItem } from '../../types/conversation'
import IconChevron from '../icons/IconChevron.vue'

const props = defineProps<{ item: ToolItem; childCount: number; sessionActive?: boolean }>()

const STATUS_LABEL: Record<SubagentStatus, string> = {
  running: 'Rodando',
  completed: 'Concluído',
  failed: 'Com erro',
  stopped: 'Parado',
}

const sub = computed(() => props.item.subagent ?? null)
const status = computed<SubagentStatus>(() => agentStatus(props.item, props.sessionActive ?? false))
const kind = computed(() => sub.value?.subagent_type || str(props.item.input.subagent_type))
const description = computed(() => sub.value?.description || str(props.item.input.description))

// Open while running, collapsed when it ends, unless the user chose.
const manual = ref<boolean | null>(null)
const open = computed(() => manual.value ?? status.value === 'running')

// The subagent strip asks to reach a card: open it, and the ones around it, and mark it.
const focus = inject(SUBAGENT_FOCUS_KEY, ref(null))
const highlighted = computed(() => focus.value?.id === props.item.id)
watch(focus, (target) => {
  if (target?.path.includes(props.item.id)) manual.value = true
})

function duration(ms: number): string {
  const total = Math.round(ms / 1000)
  const min = Math.floor(total / 60)
  const s = total % 60
  return min ? `${min} min ${s} s` : `${s} s`
}
const metrics = computed(() => {
  const usage = sub.value?.usage
  if (!usage) return []
  const parts: string[] = []
  if (usage.tool_uses != null) parts.push(`${usage.tool_uses} ${usage.tool_uses === 1 ? 'ferramenta' : 'ferramentas'}`)
  if (usage.total_tokens != null) parts.push(`${usage.total_tokens.toLocaleString('pt-BR')} tokens`)
  if (usage.duration_ms != null) parts.push(duration(usage.duration_ms))
  return parts
})
</script>

<template>
  <div
    data-test="subagent-card"
    :data-subagent-id="item.id"
    :data-highlighted="highlighted ? 'true' : undefined"
    tabindex="-1"
    class="scroll-mt-14 overflow-hidden rounded-lg border bg-panel outline-none"
    :class="[status === 'failed' ? 'border-diff-del-fg/40' : 'border-line', highlighted ? 'ring-2 ring-primary' : '']"
  >
    <div class="flex flex-col gap-1.5 px-3 py-2.5">
      <div class="flex items-center gap-2">
        <span data-test="subagent-state" :data-status="status" :aria-label="STATUS_LABEL[status]" :title="STATUS_LABEL[status]" role="img" class="flex shrink-0">
          <svg v-if="status === 'running'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" class="animate-spin text-primary" aria-hidden="true"><path d="M12 3a9 9 0 1 1-9 9" stroke-linecap="round" /></svg>
          <svg v-else-if="status === 'completed'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" class="text-primary" aria-hidden="true"><path d="M20 6 9 17l-5-5" /></svg>
          <svg v-else-if="status === 'failed'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" class="text-diff-del-fg" aria-hidden="true"><path d="M12 3 2 20h20L12 3z" /><line x1="12" y1="10" x2="12" y2="14" /></svg>
          <svg v-else width="14" height="14" viewBox="0 0 24 24" class="text-fg-subtle" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="1.5" fill="currentColor" /></svg>
        </span>
        <span class="cap text-fg">Subagente</span>
        <span v-if="kind" class="rounded bg-elevated px-1.5 py-0.5 font-mono text-xs text-fg-muted">{{ kind }}</span>
        <span class="min-w-0 grow truncate text-sm text-fg">{{ description }}</span>
      </div>
      <p v-if="status === 'running' && sub?.last_activity" class="m-0 truncate font-mono text-xs text-primary-soft">{{ sub.last_activity }}</p>
      <p v-if="metrics.length" class="m-0 font-mono text-xs text-fg-subtle">{{ metrics.join(' · ') }}</p>
      <p v-if="sub?.summary" data-test="subagent-summary" class="m-0 text-sm whitespace-pre-wrap text-fg">{{ sub.summary }}</p>
    </div>
    <template v-if="childCount > 0">
      <button
        type="button"
        data-test="subagent-toggle"
        class="flex w-full cursor-pointer items-center gap-2 border-0 border-t border-solid border-line bg-transparent px-3 py-1.5 text-left text-xs text-fg-subtle hover:bg-elevated hover:text-fg"
        :aria-expanded="open"
        @click="manual = !open"
      >
        <IconChevron :open="open" :size="12" />
        Ações ({{ childCount }})
      </button>
      <div v-show="open" data-test="subagent-children" class="flex flex-col gap-2 border-t border-line px-3 py-2.5">
        <slot />
      </div>
    </template>
  </div>
</template>
