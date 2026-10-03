<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue'
import { agentStatus, SUBAGENT_FOCUS_KEY } from '../../conversation/subagents'
import { str } from '../../conversation/tool'
import type { SubagentStatus, ToolItem } from '../../types/conversation'
import IconChevron from '../icons/IconChevron.vue'
import WorkHeader from './WorkHeader.vue'

const props = defineProps<{ item: ToolItem; childCount: number; sessionActive?: boolean }>()

// The header speaks the same words as every other action; a subagent that ended well is just "ok".
const HEADER_STATUS: Record<SubagentStatus, 'running' | 'ok' | 'error' | 'stopped'> = {
  running: 'running',
  completed: 'ok',
  failed: 'error',
  stopped: 'stopped',
}

const sub = computed(() => props.item.subagent ?? null)
const status = computed<SubagentStatus>(() => agentStatus(props.item, props.sessionActive ?? false))
const headerStatus = computed(() => HEADER_STATUS[status.value])
const kind = computed(() => sub.value?.subagent_type || str(props.item.input.subagent_type))
const description = computed(() => sub.value?.description || str(props.item.input.description))

// Collapsed by default, running or not; only the user (or the strip) opens it.
const open = ref(false)

// The subagent strip asks to reach a card: open it, and the ones around it, and mark it.
const focus = inject(SUBAGENT_FOCUS_KEY, ref(null))
const highlighted = computed(() => focus.value?.id === props.item.id)
watch(focus, (target) => {
  if (target?.path.includes(props.item.id)) open.value = true
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
    class="scroll-mt-14 overflow-hidden rounded-lg border bg-[color-mix(in_oklab,var(--color-type-agent)_9%,var(--color-panel))] outline-none"
    :class="[status === 'failed' ? 'border-diff-del-fg/40' : 'border-type-agent/40', highlighted ? 'ring-2 ring-primary' : '']"
  >
    <WorkHeader kind="agent" :tag="kind || undefined" :desc="description" :status="headerStatus" :tint="false" />
    <div v-if="(status === 'running' && sub?.last_activity) || metrics.length || sub?.summary" class="flex flex-col gap-1.5 px-3 pb-2.5">
      <p v-if="status === 'running' && sub?.last_activity" class="m-0 truncate font-mono text-xs text-secondary-soft">{{ sub.last_activity }}</p>
      <p v-if="metrics.length" class="m-0 font-mono text-xs text-fg-subtle">{{ metrics.join(' · ') }}</p>
      <p v-if="sub?.summary" data-test="subagent-summary" class="m-0 text-sm whitespace-pre-wrap text-fg">{{ sub.summary }}</p>
    </div>
    <template v-if="childCount > 0">
      <button
        type="button"
        data-test="subagent-toggle"
        class="flex w-full cursor-pointer items-center gap-2 border-0 border-t border-solid border-line bg-transparent px-3 py-1.5 text-left text-xs text-fg-subtle hover:bg-elevated hover:text-fg"
        :aria-expanded="open"
        @click="open = !open"
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
