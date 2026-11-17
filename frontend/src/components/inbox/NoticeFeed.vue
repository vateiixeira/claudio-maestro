<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import FilterChip from '../ui/FilterChip.vue'
import { errorMessage } from '../../api/http'
import { formatTime } from '../../deliveries'
import { isBareShortcut } from '../../keyboardShortcutGuard'
import { noticeDayLabel, noticeFullBody, noticeParts } from '../../noticeText'
import { useOrgStore } from '../../stores/org'
import type { Notice } from '../../types/org'
import { BTN_SMALL } from '../org/styles'

// The "Novidades" view of the Inbox: what the agents left for you, newest first, by day. A notice is selected with a
// click or with j/k; the selected one opens its actions and can show the whole text. The keys listen on the
// document only while this component is mounted, so the list of conversations keeps its own j/k.
const org = useOrgStore()
const filter = ref('all')
const selectedId = ref<number | null>(null)
const expanded = ref(false)
const busy = ref(false)
const error = ref<string | null>(null)
const askedRuns = new Set<number>()

const agentName = (id: number): string => org.byId(id)?.name ?? 'Agente'
const isUnread = (n: Notice) => n.read_at === null

const sorted = computed(() => [...org.notices].sort((a, b) => b.created_at - a.created_at || b.id - a.id))

const filters = computed(() => {
  const unread = (list: Notice[]) => list.filter(isUnread).length
  const byAgent = new Map<number, Notice[]>()
  for (const n of org.notices) byAgent.set(n.agent_id, [...(byAgent.get(n.agent_id) ?? []), n])
  const agents = [...byAgent.entries()]
    .map(([id, list]) => ({ key: `agent-${id}`, label: agentName(id), count: unread(list) }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, 'pt-BR'))
  const alerts = org.notices.filter((n) => n.kind === 'alert')
  return { total: unread(org.notices), agents, alerts: alerts.length ? unread(alerts) : null }
})
// A filter whose notices are gone (it only exists while it has any) falls back to everything.
const activeFilter = computed(() => {
  if (filter.value === 'all' || (filter.value === 'alert' && filters.value.alerts !== null)) return filter.value
  return filters.value.agents.some((a) => a.key === filter.value) ? filter.value : 'all'
})
function toggleFilter(key: string) {
  filter.value = activeFilter.value === key ? 'all' : key
}

function matches(n: Notice): boolean {
  const key = activeFilter.value
  if (key === 'all') return true
  if (key === 'alert') return n.kind === 'alert'
  return `agent-${n.agent_id}` === key
}
const visible = computed(() => sorted.value.filter(matches))
const days = computed(() => {
  const now = new Date()
  const groups: { label: string; notices: Notice[] }[] = []
  for (const n of visible.value) {
    const label = noticeDayLabel(n.created_at, now)
    const last = groups[groups.length - 1]
    if (last?.label === label) last.notices.push(n)
    else groups.push({ label, notices: [n] })
  }
  return groups
})
const unreadVisible = computed(() => visible.value.filter(isUnread))

function select(n: Notice) {
  if (selectedId.value === n.id) return
  selectedId.value = n.id
  expanded.value = false
  // The run of the notice tells which conversation to open; it is read once per agent.
  if (n.run_id !== null && org.runs[n.agent_id] === undefined && !askedRuns.has(n.agent_id)) {
    askedRuns.add(n.agent_id)
    void org.loadRuns(n.agent_id).catch(() => { askedRuns.delete(n.agent_id) })
  }
}
// The selected notice left the list (another filter): nothing stays selected.
watch(visible, (list) => {
  if (selectedId.value !== null && !list.some((n) => n.id === selectedId.value)) selectedId.value = null
})
const selected = computed(() => visible.value.find((n) => n.id === selectedId.value) ?? null)
const runSession = (n: Notice): string | null =>
  n.run_id === null ? null : (org.runs[n.agent_id]?.find((r) => r.id === n.run_id)?.session_id ?? null)

async function mark(ids: number[]) {
  if (busy.value || !ids.length) return
  busy.value = true
  error.value = null
  try {
    await org.markRead(ids)
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}

function move(step: 1 | -1) {
  const list = visible.value
  if (!list.length) return
  const current = list.findIndex((n) => n.id === selectedId.value)
  const next = current === -1 ? 0 : Math.min(list.length - 1, Math.max(0, current + step))
  select(list[next]!)
  document.querySelector(`[data-notice-id="${list[next]!.id}"]`)?.scrollIntoView?.({ block: 'nearest' })
}

function onKey(event: KeyboardEvent) {
  if (isBareShortcut(event, 'j')) {
    event.preventDefault()
    move(1)
  } else if (isBareShortcut(event, 'k')) {
    event.preventDefault()
    move(-1)
  } else if (isBareShortcut(event, 'Enter')) {
    // On a link or a button Enter already does its own thing.
    if (!selected.value || !noticeParts(selected.value.text).body || (event.target instanceof Element && event.target.closest('a, button, [role="button"]'))) return
    event.preventDefault()
    expanded.value = !expanded.value
  } else if (isBareShortcut(event, 'e')) {
    if (selected.value && isUnread(selected.value)) {
      event.preventDefault()
      void mark([selected.value.id])
    }
  }
}
onMounted(() => {
  document.addEventListener('keydown', onKey)
  // Normally the realtime load has read them; if it never got there (the projects failed first) this does, and the
  // store joins a read already under way.
  if (!org.noticesLoaded) void org.loadNotices()
})
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))

const kbdClass = 'rounded-sm border border-line-strong px-1.5 py-0.5 font-mono text-[0.6875rem] text-fg-muted'
const focusRing = 'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary'
</script>

<template>
  <p v-if="!org.noticesLoaded" data-test="notices-loading" class="m-0 py-10 text-center text-fg-muted">Carregando…</p>
  <div v-else-if="org.notices.length === 0 && org.noticesError" data-test="notices-error" role="alert" class="flex flex-col items-center gap-2 py-10 text-center">
    <p class="m-0 text-sm text-diff-del-fg">Não foi possível carregar as novidades. {{ org.noticesError }}</p>
    <button type="button" data-test="notices-retry" :class="BTN_SMALL" @click="org.loadNotices()">Tentar de novo</button>
  </div>
  <p v-else-if="org.notices.length === 0" data-test="notices-empty" class="m-0 py-10 text-center text-fg-muted">Nenhuma novidade dos agentes.</p>
  <div v-else data-test="notice-feed" class="flex flex-col gap-2">
    <div class="flex flex-wrap items-center gap-2">
      <FilterChip data-test="notice-filter" data-filter="all" label="Tudo" :count="filters.total" :pressed="activeFilter === 'all'" @toggle="filter = 'all'" />
      <FilterChip
        v-for="a in filters.agents"
        :key="a.key"
        data-test="notice-filter"
        :data-filter="a.key"
        :label="a.label"
        :count="a.count"
        :pressed="activeFilter === a.key"
        @toggle="toggleFilter(a.key)"
      />
      <FilterChip v-if="filters.alerts !== null" data-test="notice-filter" data-filter="alert" label="Pedem atenção" :count="filters.alerts" :pressed="activeFilter === 'alert'" @toggle="toggleFilter('alert')">
        <template #icon>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" class="stroke-secondary" aria-hidden="true"><path d="M12 3 2 20h20L12 3zM12 10v4M12 17v.01" /></svg>
        </template>
      </FilterChip>
      <span class="grow" />
      <button v-if="unreadVisible.length" type="button" data-test="agent-notices-read-all" :class="BTN_SMALL" :disabled="busy" @click="mark(unreadVisible.map((n) => n.id))">Marcar todas como lidas</button>
    </div>
    <p v-if="org.noticesError" data-test="notices-error" role="alert" class="m-0 flex items-center gap-2 text-sm text-diff-del-fg">Não foi possível atualizar as novidades. {{ org.noticesError }}<button type="button" data-test="notices-retry" :class="BTN_SMALL" @click="org.loadNotices()">Tentar de novo</button></p>
    <p v-if="error" data-test="agent-notices-error" role="alert" class="m-0 text-sm text-diff-del-fg">{{ error }}</p>
    <section v-for="day in days" :key="day.label" :aria-label="day.label" class="flex flex-col">
      <div class="mt-1.5 flex h-[1.875rem] items-center gap-3 px-3">
        <span data-test="notice-day" class="font-mono text-[0.6875rem] tracking-[0.08em] text-fg-subtle uppercase">{{ day.label }}</span><span class="h-px grow bg-line" />
      </div>
      <ul class="m-0 flex list-none flex-col p-0">
        <li
          v-for="n in day.notices"
          :key="n.id"
          data-test="agent-notice"
          :data-notice-id="n.id"
          :data-unread="isUnread(n) ? 'true' : 'false'"
          :data-selected="n.id === selectedId ? 'true' : 'false'"
          class="grid grid-cols-[0.875rem_6rem_minmax(0,1fr)_2.75rem] items-start gap-x-3.5 rounded-xl border px-3 py-2.5"
          :class="n.id === selectedId ? 'border-line-strong bg-panel' : 'border-transparent hover:bg-panel'"
          @click="select(n)"
        >
          <span class="flex h-[1.3125rem] items-center">
            <span v-if="n.kind === 'alert'" data-test="agent-notice-kind" data-shape="triangle" role="img" aria-label="Pede atenção" class="inline-flex">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" class="stroke-secondary" aria-hidden="true"><path d="M12 3 2 20h20L12 3zM12 10v4M12 17v.01" /></svg>
            </span>
            <span v-else-if="isUnread(n)" data-test="notice-unread-dot" class="ml-[0.1875rem] size-[0.4375rem] rounded-full bg-fg" />
          </span>
          <span data-test="agent-notice-name" class="truncate text-[0.8125rem] leading-[1.3125rem]" :class="isUnread(n) ? 'font-medium text-fg' : 'text-fg-muted'">{{ agentName(n.agent_id) }}</span>
          <div class="flex min-w-0 flex-col">
            <button
              type="button"
              data-test="agent-notice-select"
              class="m-0 block w-full min-w-0 cursor-pointer rounded-sm border-0 bg-transparent p-0 text-left"
              :class="focusRing"
              :aria-pressed="n.id === selectedId ? 'true' : 'false'"
              @click.stop="select(n)"
            >
              <span data-test="notice-headline" class="block text-sm leading-[1.3125rem] break-words" :class="isUnread(n) ? 'font-medium text-fg' : 'text-fg-muted'">{{ noticeParts(n.text).headline }}</span>
              <span
                v-if="noticeParts(n.text).body"
                data-test="agent-notice-text"
                class="mt-0.5 block text-[0.8125rem] leading-[1.1875rem] break-words"
                :class="[
                  isUnread(n) || n.id === selectedId ? 'text-fg-muted' : 'text-fg-subtle',
                  n.id === selectedId && expanded ? 'whitespace-pre-line' : 'line-clamp-2',
                ]"
              >{{ n.id === selectedId && expanded ? noticeFullBody(n.text) : noticeParts(n.text).body }}</span>
            </button>
            <div v-if="n.id === selectedId" class="mt-2.5 flex flex-wrap items-center gap-2">
              <button v-if="noticeParts(n.text).body" type="button" data-test="notice-read-full" :class="BTN_SMALL" :aria-expanded="expanded ? 'true' : 'false'" @click.stop="expanded = !expanded">{{ expanded ? 'Mostrar menos' : 'Ler tudo aqui' }}</button>
              <RouterLink v-if="org.byId(n.agent_id)" data-test="agent-notice-open" :to="{ name: 'agents', params: { projectId: org.byId(n.agent_id)!.project_id }, query: { agente: String(n.agent_id) } }" :class="[BTN_SMALL, 'inline-flex items-center no-underline']">Abrir agente</RouterLink>
              <RouterLink v-if="runSession(n)" data-test="notice-open-run" :to="{ name: 'session', params: { id: runSession(n)! } }" :class="[BTN_SMALL, 'inline-flex items-center no-underline']">Abrir conversa da execução</RouterLink>
              <span class="grow" />
              <button v-if="isUnread(n)" type="button" data-test="agent-notice-read" :class="BTN_SMALL" :disabled="busy" @click.stop="mark([n.id])">Marcar como lida</button>
            </div>
          </div>
          <span class="text-right font-mono text-[0.78125rem] leading-[1.3125rem] text-fg-subtle tabular-nums">{{ formatTime(n.created_at) }}</span>
        </li>
      </ul>
    </section>
    <p data-test="notice-keys" class="m-0 mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg-subtle">
      <span><kbd :class="kbdClass">j</kbd> <kbd :class="kbdClass">k</kbd> navegar</span>
      <span><kbd :class="kbdClass">Enter</kbd> ler aqui</span>
      <span><kbd :class="kbdClass">e</kbd> marcar como lida</span>
    </p>
  </div>
</template>
