<script setup lang="ts">
import type { PlanTask } from '../../types/api'
import IconCheck from '../icons/IconCheck.vue'
import IconCircle from '../icons/IconCircle.vue'

// One task of the panel form of the plan: the current one stands out in a box, the others stay a plain line.
defineProps<{ task: PlanTask; status: 'done' | 'current' | 'queued' }>()
const SR: Record<'done' | 'current' | 'queued', string> = { done: '(concluída)', current: '(atual)', queued: '(na fila)' }
</script>

<template>
  <li
    data-test="plan-task"
    :data-status="status"
    :aria-current="status === 'current' ? 'step' : undefined"
    class="text-sm"
    :class="{
      'flex items-baseline gap-2 text-fg-muted': status === 'done',
      'flex flex-col gap-0.5 rounded-[10px] border border-primary/30 bg-primary-tint px-2.5 py-2 text-fg': status === 'current',
      'flex items-baseline gap-2 text-fg': status === 'queued',
    }"
  >
    <template v-if="status === 'current'">
      <span aria-hidden="true" class="cap text-primary-soft">AGORA</span>
      <span class="flex items-baseline gap-2">
        <span class="shrink-0 font-mono text-xs text-fg-muted">{{ task.number }}.</span>
        <span class="min-w-0 font-medium">{{ task.title }}</span>
      </span>
    </template>
    <template v-else>
      <span aria-hidden="true" class="flex w-4 shrink-0 items-center justify-center self-center">
        <IconCheck v-if="status === 'done'" :size="12" class="text-primary" />
        <IconCircle v-else :size="12" />
      </span>
      <span class="shrink-0 font-mono text-xs">{{ task.number }}.</span>
      <span class="min-w-0">{{ task.title }}</span>
    </template>
    <span class="sr-only">{{ SR[status] }}</span>
  </li>
</template>
