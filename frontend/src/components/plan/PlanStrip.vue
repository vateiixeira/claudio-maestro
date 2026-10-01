<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { errorMessage, getSessionPlan, openInEditor } from '../../api/http'
import type { PlanTask, Session } from '../../types/api'
import { planPosition, planStopped, planVisible } from './planText'

const props = withDefaults(defineProps<{ session: Session; variant?: 'strip' | 'panel' }>(), { variant: 'strip' })
const inPanel = computed(() => props.variant === 'panel')

const plan = computed(() => props.session.plan ?? null)
const visible = computed(() => planVisible(props.session))
const stopped = computed(() => planStopped(props.session))

const open = ref(inPanel.value)
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

// In the panel the list starts open, so it loads as soon as it is shown.
onMounted(() => { if (open.value && visible.value) load() })

// A task got done or the plan file changed while the list is open: refresh it.
watch(() => [plan.value?.done, plan.value?.path], () => { if (open.value) load() })
// Another conversation starts over (the panel reopens the list).
watch(() => props.session.session_id, () => {
  open.value = inPanel.value
  requestId++
  tasks.value = []
  error.value = null
  if (open.value) load()
})

// Task numbers can repeat in a plan, so the state goes by position: the first task left is the current one.
const currentIndex = computed(() => tasks.value.findIndex((t) => !t.done))
function statusOf(task: PlanTask, index: number): 'done' | 'current' | 'queued' {
  if (task.done) return 'done'
  return index === currentIndex.value ? 'current' : 'queued'
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
    class="flex w-full flex-col gap-1.5"
    :class="inPanel ? '' : 'mx-auto max-w-[760px] px-4 pb-3'"
  >
    <div class="flex items-center gap-2">
      <button
        type="button"
        data-test="plan-toggle"
        :aria-expanded="open"
        class="flex min-w-0 grow items-baseline gap-2 rounded-md py-1 text-left text-sm hover:text-fg focus-visible:outline-2 focus-visible:outline-primary"
        @click="toggle"
      >
        <span aria-hidden="true" class="shrink-0 text-xs text-fg-subtle">{{ open ? '▾' : '▸' }}</span>
        <span class="shrink-0 truncate text-xs text-fg-subtle" :class="inPanel ? 'max-w-[45%]' : 'max-w-[35%]'">{{ plan.title }}</span>
        <span class="min-w-0 truncate text-fg">{{ planPosition(plan) }}</span>
        <span v-if="stopped" class="shrink-0 text-xs text-fg-subtle">· parado</span>
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
    <ol v-if="open && tasks.length" ref="list" class="m-0 flex list-none flex-col gap-0.5 p-0 pt-1" :class="inPanel ? '' : 'max-h-56 overflow-y-auto'">
      <li
        v-for="(task, index) in tasks"
        :key="index"
        data-test="plan-task"
        :data-status="statusOf(task, index)"
        :aria-current="statusOf(task, index) === 'current' ? 'step' : undefined"
        class="flex items-baseline gap-2 text-sm"
        :class="{
          'text-fg-muted': statusOf(task, index) === 'done',
          'font-medium text-primary-soft': statusOf(task, index) === 'current',
          'text-fg': statusOf(task, index) === 'queued',
        }"
      >
        <span aria-hidden="true" class="w-4 shrink-0 text-center text-xs">{{ marks[statusOf(task, index)] }}</span>
        <span class="shrink-0 font-mono text-xs">{{ task.number }}.</span>
        <span class="min-w-0">{{ task.title }}</span>
        <span class="sr-only">{{ { done: '(concluída)', current: '(atual)', queued: '(na fila)' }[statusOf(task, index)] }}</span>
      </li>
    </ol>
    <p v-if="error" role="alert" class="m-0 text-sm text-diff-del-fg">{{ error }}</p>
  </section>
</template>
