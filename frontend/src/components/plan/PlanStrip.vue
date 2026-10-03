<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { errorMessage, getSessionPlan, openInEditor } from '../../api/http'
import type { PlanTask, Session } from '../../types/api'
import { planPosition, planStopped, planVisible } from './planText'
import IconCheck from '../icons/IconCheck.vue'
import IconChevron from '../icons/IconChevron.vue'
import IconCircle from '../icons/IconCircle.vue'
import IconCircleDot from '../icons/IconCircleDot.vue'

const props = withDefaults(defineProps<{ session: Session; variant?: 'strip' | 'panel' }>(), { variant: 'strip' })
const inPanel = computed(() => props.variant === 'panel')

const plan = computed(() => props.session.plan ?? null)
const visible = computed(() => planVisible(props.session))
const stopped = computed(() => planStopped(props.session))

const open = ref(inPanel.value)
// Panel only: the finished tasks stay folded behind "N concluídas".
const doneOpen = ref(false)
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
    if (inPanel.value) return
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
    doneOpen.value = false
  }
}

// In the panel the list starts open, so it loads as soon as it is shown.
onMounted(() => { if (open.value && visible.value) load() })

// A task got done or the plan file changed while the list is open: refresh it.
watch(() => [plan.value?.done, plan.value?.path], () => { if (open.value) load() })
// Another conversation starts over (the panel reopens the list).
watch(() => props.session.session_id, () => {
  open.value = inPanel.value
  doneOpen.value = false
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

// Panel form: the finished tasks (folded), the current one, the next two and how many come after.
const NEXT_SHOWN = 2
const doneCount = computed(() => tasks.value.filter((t) => t.done).length)
const nextCount = computed(() => (currentIndex.value < 0 ? 0 : tasks.value.length - currentIndex.value - 1))
const laterCount = computed(() => Math.max(0, nextCount.value - NEXT_SHOWN))
const compactRows = computed(() => {
  const at = currentIndex.value
  // List empty or not loaded yet: the summary still knows the current task (index -1 is the one `statusOf` calls current).
  if (at < 0) return plan.value?.current ? [{ task: { ...plan.value.current, done: false }, index: -1 }] : []
  const rows = tasks.value.map((task, index) => ({ task, index }))
  const finished = doneOpen.value ? rows.slice(0, at) : []
  return [...finished, ...rows.slice(at, at + 1 + NEXT_SHOWN)]
})
const positionText = computed(() => (plan.value?.current ? `${plan.value.current.number} de ${plan.value.total}` : 'Concluído'))

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
    :class="inPanel ? '' : 'mx-auto max-w-(--chat-width) px-4 pb-3'"
  >
    <div class="flex items-center gap-2">
      <button
        type="button"
        data-test="plan-toggle"
        :aria-expanded="open"
        class="flex min-w-0 grow items-baseline gap-2 rounded-md py-1 text-left text-sm hover:text-fg focus-visible:outline-2 focus-visible:outline-primary"
        @click="toggle"
      >
        <IconChevron :open="open" :size="12" class="self-center text-fg-subtle" />
        <template v-if="inPanel">
          <span class="min-w-0 truncate font-medium text-fg">{{ plan.title }}</span>
          <span class="shrink-0 font-mono text-xs text-fg-muted">{{ positionText }}</span>
        </template>
        <template v-else>
          <span class="max-w-[35%] shrink-0 truncate text-xs text-fg-subtle">{{ plan.title }}</span>
          <span class="min-w-0 truncate text-fg">{{ planPosition(plan) }}</span>
        </template>
        <span v-if="stopped" class="shrink-0 text-xs text-fg-subtle">· parado</span>
      </button>
      <button
        v-if="!inPanel"
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
    <button
      v-if="inPanel && open && doneCount > 0"
      type="button"
      data-test="plan-done-toggle"
      :aria-expanded="doneOpen"
      class="flex w-fit items-center gap-1.5 rounded-md py-0.5 text-left text-xs text-fg-muted hover:text-fg focus-visible:outline-2 focus-visible:outline-primary"
      @click="doneOpen = !doneOpen"
    >
      <IconCheck :size="12" class="text-primary" />
      {{ doneCount }} {{ doneCount === 1 ? 'concluída' : 'concluídas' }}
      <IconChevron :open="doneOpen" :size="10" class="text-fg-subtle" />
    </button>
    <ol v-if="open && inPanel && compactRows.length" ref="list" class="relative m-0 flex list-none flex-col gap-1 p-0 pt-0.5">
      <li
        v-for="row in compactRows"
        :key="row.index"
        data-test="plan-task"
        :data-status="statusOf(row.task, row.index)"
        :aria-current="statusOf(row.task, row.index) === 'current' ? 'step' : undefined"
        class="text-sm"
        :class="{
          'flex items-baseline gap-2 text-fg-muted': statusOf(row.task, row.index) === 'done',
          'flex flex-col gap-0.5 rounded-[10px] border border-primary/30 bg-primary-tint px-2.5 py-2 text-fg': statusOf(row.task, row.index) === 'current',
          'flex items-baseline gap-2 text-fg': statusOf(row.task, row.index) === 'queued',
        }"
      >
        <template v-if="statusOf(row.task, row.index) === 'current'">
          <span aria-hidden="true" class="cap text-primary-soft">AGORA</span>
          <span class="flex items-baseline gap-2">
            <span class="shrink-0 font-mono text-xs text-fg-muted">{{ row.task.number }}.</span>
            <span class="min-w-0 font-medium">{{ row.task.title }}</span>
          </span>
        </template>
        <template v-else>
          <span aria-hidden="true" class="flex w-4 shrink-0 items-center justify-center self-center">
            <IconCheck v-if="statusOf(row.task, row.index) === 'done'" :size="12" class="text-primary" />
            <IconCircle v-else :size="12" />
          </span>
          <span class="shrink-0 font-mono text-xs">{{ row.task.number }}.</span>
          <span class="min-w-0">{{ row.task.title }}</span>
        </template>
        <span class="sr-only">{{ { done: '(concluída)', current: '(atual)', queued: '(na fila)' }[statusOf(row.task, row.index)] }}</span>
      </li>
    </ol>
    <p v-if="inPanel && open && laterCount > 0" data-test="plan-later" class="m-0 text-xs text-fg-subtle">+{{ laterCount }} depois</p>
    <ol v-if="open && !inPanel && tasks.length" ref="list" class="relative m-0 flex max-h-56 list-none flex-col gap-0.5 overflow-y-auto p-0 pt-1">
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
        <span aria-hidden="true" class="flex w-4 shrink-0 items-center justify-center self-center">
          <IconCheck v-if="statusOf(task, index) === 'done'" :size="12" />
          <IconCircleDot v-else-if="statusOf(task, index) === 'current'" :size="12" />
          <IconCircle v-else :size="12" />
        </span>
        <span class="shrink-0 font-mono text-xs">{{ task.number }}.</span>
        <span class="min-w-0">{{ task.title }}</span>
        <span class="sr-only">{{ { done: '(concluída)', current: '(atual)', queued: '(na fila)' }[statusOf(task, index)] }}</span>
      </li>
    </ol>
    <div v-if="inPanel" data-test="plan-footer" class="flex flex-wrap items-start gap-1.5 pt-0.5">
      <button
        type="button"
        data-test="plan-open"
        class="h-7 shrink-0 cursor-pointer rounded-md border border-line-strong px-2 text-xs text-fg hover:bg-card focus-visible:outline-2 focus-visible:outline-primary"
        @click="openPlan"
      >Abrir plano</button>
      <slot name="actions" />
    </div>
    <p v-if="error" role="alert" class="m-0 text-sm text-diff-del-fg">{{ error }}</p>
  </section>
</template>
