<!-- frontend/src/components/context/ContextBreakdown.vue -->
<script lang="ts">
import type { ContextBreakdown as Breakdown } from '../../types/api'

/** What the backend last measured. `live` false: kept in memory, answered with no process running. */
interface Measured {
  breakdown: Breakdown
  live: boolean
  /** Unix seconds; null when the backend sent nothing usable. */
  at: number | null
}

/** Last breakdown per session, so reopening the popover or the panel shows it at once while the new one is read. */
const lastBreakdown = new Map<string, Measured>()
</script>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId, watch } from 'vue'
import { getSessionContext } from '../../api/http'
import { contextLayout } from '../../contextLayout'
import { formatMeasuredAt, formatTokens } from '../../format'
import type { ContextDetailsResponse, ContextUnavailableReason, ContextUsage } from '../../types/api'

const props = defineProps<{
  sessionId: string
  context: ContextUsage | null
  variant: 'popover' | 'panel'
}>()

const CLOSED_PHRASE = 'O detalhamento aparece depois da próxima mensagem desta conversa.'
const ERROR_PHRASE = 'Não foi possível calcular o detalhamento agora.'

const uid = useId()
const measured = ref<Measured | null>(null)
const breakdown = computed(() => measured.value?.breakdown ?? null)
const loading = ref(false)
const failure = ref<ContextUnavailableReason | null>(null)
// Total the backend knew when it could not read the details; the fallback when the prop is empty.
const knownContext = ref<ContextUsage | null>(null)
const opened = ref<string[]>([])

// One request at a time. A request asked for while another runs only marks `again`, and runs once at the end.
// `generation` changes with the session: answers of an older generation are dropped.
let generation = 0
let running = false
let again = false
let controller: AbortController | null = null

async function run() {
  const mine = generation
  const id = props.sessionId
  running = true
  loading.value = true
  controller = new AbortController()
  let response: ContextDetailsResponse | null
  try {
    response = await getSessionContext(id, controller.signal)
  } catch {
    response = null
  }
  if (mine !== generation) return
  if (response?.available) {
    const at: unknown = response.measured_at
    measured.value = {
      breakdown: response.breakdown,
      live: response.live,
      at: typeof at === 'number' && !Number.isNaN(new Date(at * 1000).getTime()) ? at : null,
    }
    lastBreakdown.set(id, measured.value)
    failure.value = null
    knownContext.value = response.context
  } else if (response) {
    failure.value = response.reason
    knownContext.value = response.context
  } else {
    failure.value = 'failed'
  }
  running = false
  loading.value = false
  if (again) {
    again = false
    void run()
  }
}

function request() {
  if (running) again = true
  else void run()
}

function switchSession() {
  generation++
  controller?.abort()
  running = false
  again = false
  measured.value = lastBreakdown.get(props.sessionId) ?? null
  failure.value = null
  knownContext.value = null
  opened.value = []
  void run()
}

watch(
  [() => props.sessionId, () => props.context?.used_tokens],
  ([id], old) => {
    if (!old || id !== old[0]) switchSession()
    else request()
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  generation++
  controller?.abort()
})

const layout = computed(() => (breakdown.value ? contextLayout(breakdown.value) : null))

/** The total in the header: the breakdown's when there is one, otherwise what the session already knew. */
const total = computed(() => {
  const b = breakdown.value
  if (b) return { percent: b.percent, used: b.total_tokens, max: b.max_tokens }
  const c = props.context ?? knownContext.value
  return c ? { percent: c.percent, used: c.used_tokens, max: c.max_tokens } : null
})
const percentLabel = computed(() => (total.value ? `${Math.round(total.value.percent)}% usado` : ''))
const tokensLabel = computed(() => (total.value ? `${formatTokens(total.value.used)} / ${formatTokens(total.value.max)}` : ''))
const barLabel = computed(() => (total.value ? `Contexto: ${percentLabel.value}, ${tokensLabel.value}` : ''))

// The time shows for a kept reading, and for any reading once the session has no process any more.
const measuredLabel = computed(() => {
  const m = measured.value
  if (!m || m.at === null) return null
  return !m.live || failure.value === 'no_process' ? formatMeasuredAt(m.at) : null
})

const message = computed(() => {
  if (failure.value === 'no_process') return breakdown.value ? null : CLOSED_PHRASE
  if (failure.value) return ERROR_PHRASE
  return loading.value && !breakdown.value ? 'Calculando…' : null
})

function toggle(key: string) {
  opened.value = opened.value.includes(key) ? opened.value.filter((k) => k !== key) : [...opened.value, key]
}
// The deferred rows come last; a rule separates them from the rest.
function separated(index: number): boolean {
  const rows = layout.value?.rows ?? []
  return index > 0 && rows[index].muted && !rows[index - 1].muted
}
</script>

<template>
  <div data-test="ctx-root" :data-variant="variant" class="flex min-w-0 flex-col">
    <div v-if="total" class="mb-2 flex items-baseline justify-between gap-3">
      <b data-test="ctx-percent" class="font-medium whitespace-nowrap" :class="variant === 'popover' ? 'text-[0.9375rem]' : 'text-[0.8125rem]'">{{ percentLabel }}</b>
      <span data-test="ctx-tokens" class="font-mono text-xs whitespace-nowrap text-fg-subtle tabular-nums">{{ tokensLabel }}</span>
    </div>

    <div
      v-if="total"
      data-test="ctx-bar"
      role="img"
      :aria-label="barLabel"
      class="mb-3 flex h-1.5 gap-px overflow-hidden rounded-full bg-elevated"
    >
      <template v-if="layout">
        <i
          v-for="segment in layout.segments"
          :key="segment.key"
          data-test="ctx-segment"
          :title="`${segment.label}: ${formatTokens(segment.tokens)}`"
          class="block h-full"
          :style="{ width: `${segment.width}%`, background: segment.color }"
        />
      </template>
      <i v-else class="block h-full bg-fg-muted" :style="{ width: `${Math.min(Math.max(total.percent, 0), 100)}%` }" />
    </div>

    <ul v-if="layout" class="m-0 flex list-none flex-col gap-0.5 p-0" aria-label="Detalhamento do contexto">
      <template v-for="(row, index) in layout.rows" :key="row.key">
        <li v-if="separated(index)" role="separator" class="my-1.5 h-px bg-line" />
        <li data-test="ctx-row" class="list-none">
          <component
            :is="row.details ? 'button' : 'div'"
            :type="row.details ? 'button' : undefined"
            :data-test="row.details ? 'ctx-toggle' : undefined"
            :aria-expanded="row.details ? opened.includes(row.key) : undefined"
            :aria-controls="row.details ? `${uid}-${index}` : undefined"
            class="group grid w-full grid-cols-[10px_minmax(0,1fr)_auto_3rem] items-center gap-2 rounded-sm px-1 py-0.5 text-left text-[0.78rem] text-fg"
            :class="row.details ? 'cursor-pointer hover:bg-elevated' : ''"
            @click="row.details && toggle(row.key)"
          >
            <span
              class="h-2.5 w-2.5 rounded-[2px]"
              :class="row.color === 'var(--color-elevated)' ? 'outline outline-1 outline-line-strong' : ''"
              :style="{ background: row.color }"
            />
            <span
              class="truncate"
              :class="[
                row.muted ? 'text-fg-subtle' : '',
                row.details ? 'underline decoration-fg-subtle decoration-dotted underline-offset-[3px] group-hover:decoration-solid' : '',
              ]"
            >{{ row.label }}</span>
            <span class="text-right font-mono text-fg-subtle tabular-nums">{{ formatTokens(row.tokens) }}</span>
            <span class="text-right font-mono tabular-nums" :class="row.muted ? 'text-fg-subtle' : ''">{{ row.percentText }}</span>
          </component>
          <ul
            v-if="row.details && opened.includes(row.key)"
            :id="`${uid}-${index}`"
            data-test="ctx-details"
            class="scroll-thin m-0 mt-0.5 mb-1.5 ml-[18px] flex max-h-[9.5rem] list-none flex-col gap-px overflow-y-auto rounded-lg px-2 py-1.5"
            :class="variant === 'popover' ? 'bg-panel' : 'bg-card'"
          >
            <li v-for="(detail, i) in row.details" :key="i" class="flex justify-between gap-3 py-px text-xs text-fg-muted">
              <span class="truncate" :title="detail.label">{{ detail.label }}</span>
              <span class="shrink-0 font-mono tabular-nums">{{ formatTokens(detail.tokens) }}</span>
            </li>
          </ul>
        </li>
      </template>
    </ul>

    <p v-if="measuredLabel" data-test="ctx-measured" class="m-0 text-[0.71875rem] text-fg-subtle" :class="layout ? 'mt-2.5' : ''">{{ measuredLabel }}</p>
    <p v-if="message" data-test="ctx-message" role="status" class="m-0 text-[0.71875rem] text-fg-subtle" :class="layout ? 'mt-2.5' : ''">{{ message }}</p>
  </div>
</template>
