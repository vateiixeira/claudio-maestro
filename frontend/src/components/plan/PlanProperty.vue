<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { errorMessage, getSessionPlan, linkSessionPlan, listProjectPlans, unlinkSessionPlan } from '../../api/http'
import { useSessionsStore } from '../../stores/sessions'
import type { PlanState, ProjectPlan } from '../../types/api'

const props = defineProps<{ sessionId: string; projectId: number }>()

const sessions = useSessionsStore()

const state = ref<PlanState | null>(null)
const busy = ref(false)
const error = ref<string | null>(null)
const menuOpen = ref(false)
const plans = ref<ProjectPlan[]>([])
const loadingPlans = ref(false)
const root = ref<HTMLElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)
const menu = ref<HTMLElement | null>(null)

// The store's summary changes with `session.updated`; the full state (with tasks) is fetched again then.
const planKey = computed(() => JSON.stringify(sessions.find(props.sessionId)?.plan ?? null))

// Only the newest state wins: an older response arriving late is dropped.
let ticket = 0

async function load() {
  const mine = ++ticket
  const id = props.sessionId
  try {
    const fresh = await getSessionPlan(id)
    if (mine !== ticket || id !== props.sessionId) return
    state.value = fresh
    error.value = null
  } catch (e) {
    if (mine !== ticket || id !== props.sessionId) return
    error.value = errorMessage(e)
  }
}

watch(() => props.sessionId, () => {
  state.value = null
  error.value = null
  hideMenu(false)
})
watch(() => `${props.sessionId}\n${planKey.value}`, () => { void load() }, { immediate: true })

async function act(call: () => Promise<PlanState>) {
  if (busy.value) return
  busy.value = true
  error.value = null
  const id = props.sessionId
  try {
    const next = await call()
    if (id !== props.sessionId) return
    ticket++
    state.value = next
  } catch (e) {
    if (id === props.sessionId) error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}

const unlink = () => act(() => unlinkSessionPlan(props.sessionId))
const linkAuto = () => act(() => linkSessionPlan(props.sessionId, { auto: true }))
function choose(path: string) {
  hideMenu()
  void act(() => linkSessionPlan(props.sessionId, { path }))
}

const items = () => Array.from(menu.value?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])

async function showMenu() {
  error.value = null
  loadingPlans.value = true
  try {
    plans.value = await listProjectPlans(props.projectId)
  } catch (e) {
    error.value = errorMessage(e)
    return
  } finally {
    loadingPlans.value = false
  }
  menuOpen.value = true
  document.addEventListener('pointerdown', onOutside)
  await nextTick()
  items()[0]?.focus()
}

function hideMenu(returnFocus = true) {
  menuOpen.value = false
  document.removeEventListener('pointerdown', onOutside)
  if (returnFocus) trigger.value?.focus()
}

function onOutside(event: Event) {
  if (!root.value?.contains(event.target as Node)) hideMenu(false)
}
onBeforeUnmount(() => document.removeEventListener('pointerdown', onOutside))

function toggleMenu() {
  if (menuOpen.value) hideMenu()
  else if (!loadingPlans.value) void showMenu()
}

// Focus stays on the trigger when the list is empty (no item to take it), so Esc is also handled
// on the whole property: the drawer around the panel must not see an Esc that closed our notice.
function onRootKey(event: KeyboardEvent) {
  if (event.key !== 'Escape' || !menuOpen.value || event.defaultPrevented) return
  event.preventDefault()
  event.stopPropagation()
  hideMenu()
}

function onMenuKey(event: KeyboardEvent) {
  const list = items()
  const current = list.indexOf(document.activeElement as HTMLElement)
  let next: number | null = null
  if (event.key === 'ArrowDown') next = list.length ? (current + 1) % list.length : null
  else if (event.key === 'ArrowUp') next = list.length ? (current - 1 + list.length) % list.length : null
  else if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = list.length - 1
  else if (event.key === 'Escape') {
    // Only the list closes: the drawer around the panel must not see this Esc.
    event.preventDefault()
    event.stopPropagation()
    hideMenu()
    return
  } else if (event.key === 'Tab') {
    hideMenu(false)
    return
  }
  if (next !== null && list.length) {
    event.preventDefault()
    list[next]?.focus()
  }
}

const plan = computed(() => state.value?.plan ?? null)
// The plan is linked (there is a path) but its summary is gone: deleted, unreadable or without tasks.
const unavailable = computed(() => state.value != null && plan.value == null && !!state.value.path)
const hasLink = computed(() => state.value != null && (plan.value != null || !!state.value.path))
const isOff = computed(() => state.value?.link === 'off')

function shortPath(path: string): string {
  const i = path.indexOf('/docs/')
  return i >= 0 ? path.slice(i + 1) : path
}
</script>

<template>
  <dt class="text-fg-muted">Plano</dt>
  <dd ref="root" data-test="prop-plan" class="m-0 flex min-w-0 flex-col gap-1.5" @keydown="onRootKey">
    <template v-if="plan">
      <span class="truncate" :title="plan.path">{{ plan.title }}</span>
      <span class="text-fg-muted">{{ plan.current ? `${plan.current.number} de ${plan.total}` : 'Concluído' }}</span>
    </template>
    <template v-else-if="unavailable && state?.path">
      <span class="text-secondary">Plano indisponível</span>
      <span class="break-all font-mono text-xs text-fg-muted" :title="state.path">{{ shortPath(state.path) }}</span>
    </template>
    <span v-else class="text-fg-muted">{{ state ? 'Nenhum' : '…' }}</span>

    <div v-if="state" class="flex flex-wrap gap-1.5">
      <button
        ref="trigger"
        type="button"
        aria-haspopup="menu"
        :aria-expanded="menuOpen"
        :disabled="busy || loadingPlans"
        class="h-7 cursor-pointer rounded-md border border-line-strong bg-transparent px-2 text-xs text-fg hover:bg-card focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-default disabled:opacity-60"
        @click="toggleMenu"
      >{{ hasLink ? 'Trocar plano…' : 'Escolher plano…' }}</button>
      <button
        v-if="hasLink"
        type="button"
        :disabled="busy"
        class="h-7 cursor-pointer rounded-md border border-line-strong bg-transparent px-2 text-xs text-fg hover:bg-card focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-default disabled:opacity-60"
        @click="unlink"
      >Desligar</button>
      <button
        v-if="isOff"
        type="button"
        :disabled="busy"
        class="h-7 cursor-pointer rounded-md border border-line-strong bg-transparent px-2 text-xs text-fg hover:bg-card focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-default disabled:opacity-60"
        @click="linkAuto"
      >Ligar automaticamente</button>
    </div>

    <p v-if="menuOpen && plans.length === 0" role="status" class="m-0 rounded-lg border border-line-strong bg-elevated px-2.5 py-1.5 text-xs text-fg-muted">Nenhum plano em docs/superpowers/plans/</p>
    <div
      v-else-if="menuOpen"
      ref="menu"
      role="menu"
      aria-label="Planos do projeto"
      class="flex max-h-60 flex-col overflow-y-auto rounded-lg border border-line-strong bg-card p-1 shadow-lg"
      @keydown="onMenuKey"
    >
      <button
        v-for="item in plans"
        :key="item.path"
        type="button"
        role="menuitem"
        tabindex="-1"
        :disabled="busy"
        :title="item.path"
        class="flex cursor-pointer items-center justify-between gap-2 rounded-md px-2.5 py-1.5 text-left text-sm text-fg hover:bg-elevated focus:bg-elevated focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-fg-muted disabled:cursor-default disabled:opacity-60"
        :class="item.path === state?.path ? 'text-fg font-semibold' : ''"
        @click="choose(item.path)"
      >
        <span class="min-w-0 truncate">{{ item.title }}</span>
        <span class="shrink-0 font-mono text-xs text-fg-muted">{{ item.done }}/{{ item.total }}</span>
      </button>
    </div>

    <p v-if="error" role="alert" class="m-0 text-xs text-secondary">{{ error }}</p>
    <button
      v-if="!state && error"
      type="button"
      class="h-7 w-fit cursor-pointer rounded-md border border-line-strong bg-transparent px-2 text-xs text-fg hover:bg-card focus-visible:outline-2 focus-visible:outline-primary"
      @click="load"
    >Tentar de novo</button>
  </dd>
</template>
