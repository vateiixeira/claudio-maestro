<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { errorMessage } from '../../api/http'
import { formatActivity } from '../../format'
import { useSpecialistsStore } from '../../stores/specialists'
import type { SpecialistNoticeKind } from '../../types/api'
import { BTN_SMALL } from '../agents/styles'

// The notices the agents left for you: shown above the Inbox tabs while there is any unread. Each one can be
// marked as read, or all at once; the text is cut at three lines and opens on click.
const specialists = useSpecialistsStore()
const unread = computed(() => specialists.notices.filter((n) => n.read_at === null))
const expanded = ref<Set<number>>(new Set())
const error = ref<string | null>(null)
const busy = ref(false)

const SHAPES: Record<SpecialistNoticeKind, { shape: 'check' | 'triangle' | 'dot'; label: string }> = {
  summary: { shape: 'check', label: 'Resumo' },
  alert: { shape: 'triangle', label: 'Alerta' },
  notice: { shape: 'dot', label: 'Aviso' },
}

function agentName(id: number): string {
  return specialists.byId(id)?.name ?? 'Agente'
}
function toggle(id: number) {
  const next = new Set(expanded.value)
  if (!next.delete(id)) next.add(id)
  expanded.value = next
}
async function mark(ids: number[]) {
  if (busy.value) return
  busy.value = true
  error.value = null
  try {
    await specialists.markRead(ids)
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section v-if="unread.length > 0" data-test="agent-notices" aria-labelledby="agent-notices-title" class="flex flex-col gap-1 rounded-lg border border-line bg-surface p-3">
    <div class="flex items-center gap-3">
      <h2 id="agent-notices-title" class="m-0 grow font-mono text-[0.6875rem] font-normal tracking-[0.08em] text-fg-subtle uppercase">Avisos dos agentes</h2>
      <button type="button" data-test="agent-notices-read-all" :class="BTN_SMALL" :disabled="busy" @click="mark(unread.map((n) => n.id))">Marcar todos como lidos</button>
    </div>
    <p v-if="error" data-test="agent-notices-error" role="alert" class="m-0 text-sm text-diff-del-fg">{{ error }}</p>
    <ul class="m-0 flex list-none flex-col p-0">
      <li v-for="n in unread" :key="n.id" data-test="agent-notice" class="flex items-start gap-3 border-t border-line py-2 first:border-t-0">
        <span
          data-test="agent-notice-kind"
          :data-shape="SHAPES[n.kind].shape"
          class="mt-0.5 inline-flex size-4 shrink-0 items-center justify-center"
          role="img"
          :aria-label="SHAPES[n.kind].label"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path v-if="SHAPES[n.kind].shape === 'check'" d="M5 12.5 10 17 19 7" class="stroke-primary" />
            <g v-else-if="SHAPES[n.kind].shape === 'triangle'" class="stroke-secondary">
              <path d="M12 3 2 20h20L12 3z" /><line x1="12" y1="10" x2="12" y2="14" /><line x1="12" y1="17" x2="12" y2="17.01" />
            </g>
            <circle v-else cx="12" cy="12" r="4" class="fill-fg-subtle stroke-fg-subtle" />
          </svg>
        </span>
        <div class="flex min-w-0 grow flex-col gap-0.5">
          <div class="flex items-baseline gap-2 text-xs text-fg-muted">
            <span data-test="agent-notice-name" class="font-medium text-fg">{{ agentName(n.specialist_id) }}</span>
            <span>{{ formatActivity(n.created_at) }}</span>
          </div>
          <button
            type="button"
            data-test="agent-notice-text"
            :aria-expanded="expanded.has(n.id)"
            title="Clique para ver o texto inteiro"
            class="m-0 cursor-pointer border-0 bg-transparent p-0 text-left text-sm break-words whitespace-pre-wrap text-fg focus-visible:outline-2 focus-visible:outline-primary"
            :class="expanded.has(n.id) ? '' : 'line-clamp-3'"
            @click="toggle(n.id)"
          >{{ n.text }}</button>
        </div>
        <div class="flex shrink-0 items-center gap-2">
          <RouterLink v-if="n.session_id" data-test="agent-notice-open" :to="`/sessions/${n.session_id}`" class="text-xs text-primary-soft">Abrir conversa</RouterLink>
          <button type="button" data-test="agent-notice-read" :class="BTN_SMALL" :disabled="busy" @click="mark([n.id])">Marcar como lido</button>
        </div>
      </li>
    </ul>
  </section>
</template>
