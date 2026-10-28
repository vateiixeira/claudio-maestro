<script setup lang="ts">
import { computed } from 'vue'
import DecisionCard from './DecisionCard.vue'
import ShapeIcon from './ShapeIcon.vue'
import { formatRunDate, type StateShape } from '../../../org'
import type { CiReceipt, TaskDetail, TaskPr } from '../../../types/org'

// What surrounds the task: the decisions it asks of the person, the pull requests and the CI receipts.
const props = defineProps<{ detail: TaskDetail }>()

const decisions = computed(() => [...props.detail.decisions].sort((a, b) => Number(b.status === 'pending') - Number(a.status === 'pending') || b.created_at - a.created_at))
const prs = computed(() => props.detail.prs)
const ci = computed(() => [...props.detail.ci].sort((a, b) => b.created_at - a.created_at))
const empty = computed(() => decisions.value.length === 0 && prs.value.length === 0 && ci.value.length === 0)

/** Only web links are links; anything else an agent wrote stays plain text. */
const safe = (url: string | null): boolean => url !== null && /^https?:\/\//i.test(url)

function prLabel(pr: TaskPr): string {
  const match = /^https?:\/\/[^/]+\/([^/]+\/[^/]+)\/pull\/(\d+)/.exec(pr.url)
  return match ? `${match[1]} #${match[2]}` : pr.url
}

const CONCLUSIONS: Record<string, { label: string; shape: StateShape }> = {
  success: { label: 'Passou', shape: 'check' },
  failure: { label: 'Falhou', shape: 'cross' },
  timed_out: { label: 'Falhou por tempo', shape: 'cross' },
  cancelled: { label: 'Cancelado', shape: 'dash' },
  skipped: { label: 'Pulado', shape: 'dash' },
  neutral: { label: 'Neutro', shape: 'dash' },
  action_required: { label: 'Pede ação', shape: 'triangle' },
}

function conclusion(receipt: CiReceipt): { label: string; shape: StateShape } {
  if (receipt.conclusion === null) return { label: 'Em andamento', shape: 'spinner' }
  return CONCLUSIONS[receipt.conclusion] ?? { label: receipt.conclusion, shape: 'circle' }
}
</script>

<template>
  <div class="flex min-w-0 flex-col gap-5">
    <section v-if="decisions.length" aria-labelledby="task-decisions-title" class="flex flex-col gap-2">
      <h2 id="task-decisions-title" class="m-0 text-sm font-semibold">Decisões</h2>
      <ul aria-labelledby="task-decisions-title" class="m-0 flex list-none flex-col gap-2 p-0">
        <li v-for="decision in decisions" :key="decision.id"><DecisionCard :decision="decision" /></li>
      </ul>
    </section>

    <section v-if="prs.length" aria-labelledby="task-prs-title" class="flex flex-col gap-2">
      <h2 id="task-prs-title" class="m-0 text-sm font-semibold">Pull requests</h2>
      <ul aria-labelledby="task-prs-title" class="m-0 flex list-none flex-col gap-1 p-0 text-sm">
        <li v-for="pr in prs" :key="pr.url" class="flex min-w-0 items-baseline gap-2">
          <a v-if="safe(pr.url)" data-test="task-pr" :href="pr.url" target="_blank" rel="noopener noreferrer" class="min-w-0 rounded text-info-soft [overflow-wrap:anywhere] hover:underline focus-visible:outline-2 focus-visible:outline-primary">{{ prLabel(pr) }}</a>
          <span v-else data-test="task-pr" class="min-w-0 text-fg-muted [overflow-wrap:anywhere]">{{ pr.url }}</span>
          <span v-if="pr.closed" class="shrink-0 text-xs text-fg-subtle">Fechado</span>
        </li>
      </ul>
    </section>

    <section v-if="ci.length" aria-labelledby="task-ci-title" class="flex flex-col gap-2">
      <h2 id="task-ci-title" class="m-0 text-sm font-semibold">Verificações (CI)</h2>
      <ul aria-labelledby="task-ci-title" class="m-0 flex list-none flex-col gap-1.5 p-0 text-sm">
        <li v-for="receipt in ci" :key="receipt.id" data-test="task-ci" class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
          <span class="inline-flex items-center gap-1.5" :data-shape="conclusion(receipt).shape">
            <ShapeIcon :shape="conclusion(receipt).shape" />
            <span>{{ conclusion(receipt).label }}</span>
          </span>
          <span v-if="receipt.head_sha" class="font-mono text-xs text-fg-subtle">{{ receipt.head_sha.slice(0, 7) }}</span>
          <a v-if="safe(receipt.run_url)" :href="receipt.run_url!" target="_blank" rel="noopener noreferrer" class="rounded text-xs text-info-soft hover:underline focus-visible:outline-2 focus-visible:outline-primary">Ver execução</a>
          <time class="ml-auto text-xs text-fg-subtle" :datetime="new Date(receipt.created_at * 1000).toISOString()">{{ formatRunDate(receipt.created_at) }}</time>
        </li>
      </ul>
    </section>

    <p v-if="empty" data-test="sidebar-empty" class="m-0 text-sm text-fg-subtle">Sem decisões, pull requests nem verificações por enquanto.</p>
  </div>
</template>
