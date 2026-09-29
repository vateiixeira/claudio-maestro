<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { errorMessage, getSessionPlan, openInEditor } from '../../api/http'
import type { PlanTask, Session } from '../../types/api'
import { planPosition, planStopped, planVisible } from './planText'

const props = defineProps<{ session: Session }>()

const plan = computed(() => props.session.plan ?? null)
const visible = computed(() => planVisible(props.session))
const stopped = computed(() => planStopped(props.session))

const open = ref(false)
const tasks = ref<PlanTask[]>([])
const error = ref<string | null>(null)
const list = ref<HTMLElement | null>(null)

// Drops answers of an older request when a newer one was started or the list was closed.
let requestId = 0
async function load() {
  const mine = ++requestId
  try {
    const state = await getSessionPlan(props.session.session_id)
    if (mine !== requestId || !open.value) return
    tasks.value = state.tasks
    error.value = null
    await nextTick()
    list.value?.querySelector('[data-status="current"]')?.scrollIntoView({ block: 'nearest' })
  } catch (e) {
    if (mine !== requestId) return
    error.value = errorMessage(e)
  }
}

function toggle() {
  open.value = !open.value
  if (open.value) {
    error.value = null
    load()
  } else {
    requestId++
    tasks.value = []
  }
}

// A task got done while the list is open: refresh it.
watch(() => plan.value?.done, () => { if (open.value) load() })
// Another conversation or a plan that went away starts over.
watch(() => props.session.session_id, () => {
  open.value = false
  requestId++
  tasks.value = []
  error.value = null
})

function statusOf(task: PlanTask): 'done' | 'current' | 'queued' {
  if (task.done) return 'done'
  return task.number === plan.value?.current?.number ? 'current' : 'queued'
}
const marks = { done: '✓', current: '●', queued: '○' } as const

async function openPlan() {
  if (!plan.value) return
  try {
    await openInEditor(plan.value.path)
    error.value = null
  } catch (e) {
    error.value = errorMessage(e)
  }
}
</script>

<template>
  <section
    v-if="visible && plan"
    data-test="plan-strip"
    aria-label="Plano"
    class="mx-auto flex w-full max-w-[760px] flex-col gap-1.5 px-4 pb-3"
    :class="stopped ? 'opacity-60' : ''"
  >
    <div class="flex items-center gap-2">
      <button
        type="button"
        data-test="plan-toggle"
        :aria-expanded="open"
        class="flex min-w-0 grow items-baseline gap-2 rounded-md py-1 text-left text-sm hover:text-fg focus-visible:outline-2 focus-visible:outline-primary"
        @click="toggle"
      >
        <span aria-hidden="true" class="shrink-0 text-xs text-fg-muted">{{ open ? '▾' : '▸' }}</span>
        <span class="max-w-[35%] shrink-0 truncate text-xs text-fg-muted">{{ plan.title }}</span>
        <span class="min-w-0 truncate text-fg">{{ planPosition(plan) }}</span>
        <span v-if="stopped" class="shrink-0 text-xs text-fg-muted">· parado</span>
      </button>
      <button
        type="button"
        data-test="plan-open"
        class="h-7 shrink-0 rounded-md border border-line-strong px-2.5 text-xs text-fg-muted hover:bg-card hover:text-fg"
        @click="openPlan"
      >Abrir plano</button>
    </div>
    <div
      role="progressbar"
      aria-label="Progresso do plano"
      aria-valuemin="0"
      :aria-valuenow="plan.done"
      :aria-valuemax="plan.total"
      class="h-1 w-full overflow-hidden rounded-full bg-line"
    >
      <div
        class="h-full rounded-full transition-[width]"
        :class="stopped ? 'bg-fg-muted' : 'bg-primary'"
        :style="{ width: plan.total > 0 ? `${Math.min(100, (plan.done / plan.total) * 100)}%` : '0%' }"
      />
    </div>
    <ol v-if="open && tasks.length" ref="list" class="m-0 flex max-h-56 list-none flex-col gap-0.5 overflow-y-auto p-0 pt-1">
      <li
        v-for="task in tasks"
        :key="task.number"
        data-test="plan-task"
        :data-status="statusOf(task)"
        :aria-current="statusOf(task) === 'current' ? 'step' : undefined"
        class="flex items-baseline gap-2 text-sm"
        :class="{
          'text-fg-muted': statusOf(task) === 'done',
          'font-medium text-primary-soft': statusOf(task) === 'current',
          'text-fg': statusOf(task) === 'queued',
        }"
      >
        <span aria-hidden="true" class="w-4 shrink-0 text-center text-xs">{{ marks[statusOf(task)] }}</span>
        <span class="shrink-0 font-mono text-xs">{{ task.number }}.</span>
        <span class="min-w-0">{{ task.title }}</span>
        <span class="sr-only">{{ { done: '(concluída)', current: '(atual)', queued: '(na fila)' }[statusOf(task)] }}</span>
      </li>
    </ol>
    <p v-if="error" role="alert" class="m-0 text-sm text-secondary-soft">{{ error }}</p>
  </section>
</template>
