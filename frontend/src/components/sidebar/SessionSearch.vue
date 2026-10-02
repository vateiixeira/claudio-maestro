<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import { needsYou } from '../../conversation/needsYou'
import { errorMessage, searchSessions } from '../../api/http'
import { formatActivity } from '../../format'
import { displayStateLabel } from '../../sessionState'
import { useProjectsStore } from '../../stores/projects'
import type { Session } from '../../types/api'

const DELAY = 250

const projects = useProjectsStore()
const router = useRouter()

const query = ref('')
const results = ref<Session[]>([])
const searched = ref(false)
const error = ref<string | null>(null)
const input = ref<HTMLInputElement | null>(null)

let timer: ReturnType<typeof setTimeout> | null = null
// Each query takes a ticket; only the answer to the newest one is shown.
let ticket = 0

function reset(): void {
  if (timer) clearTimeout(timer)
  timer = null
  ticket++
  results.value = []
  searched.value = false
  error.value = null
}

watch(query, (value) => {
  reset()
  const q = value.trim()
  if (!q) return
  timer = setTimeout(() => void run(q), DELAY)
})

async function run(q: string): Promise<void> {
  timer = null
  const mine = ++ticket
  try {
    const found = await searchSessions(q)
    if (mine !== ticket) return
    results.value = found
    error.value = null
  } catch (e) {
    if (mine !== ticket) return
    results.value = []
    error.value = errorMessage(e)
  }
  searched.value = true
}

function open(session: Session): void {
  void router.push({ name: 'session', params: { id: session.session_id } })
}

function clear(): void {
  query.value = ''
  reset()
}

function onEnter(): void {
  const first = results.value[0]
  if (first) open(first)
}

function onGlobalKey(event: KeyboardEvent): void {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    input.value?.focus()
    input.value?.select()
  }
}

onMounted(() => window.addEventListener('keydown', onGlobalKey))
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onGlobalKey)
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <div class="flex flex-col gap-2">
    <div class="flex h-9 items-center gap-2 rounded-lg border border-line bg-panel px-2.5 focus-within:border-fg-muted">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 text-fg-muted" aria-hidden="true">
        <circle cx="11" cy="11" r="7" />
        <line x1="21" y1="21" x2="16.5" y2="16.5" />
      </svg>
      <label for="session-search" class="sr-only">Procurar sessões</label>
      <input
        id="session-search"
        ref="input"
        v-model="query"
        data-test="search-input"
        type="search"
        placeholder="Procurar sessões"
        autocomplete="off"
        class="h-8 min-w-0 grow border-none bg-transparent text-[13.5px] text-fg outline-none placeholder:text-fg-muted"
        @keydown.enter.prevent="onEnter"
        @keydown.esc.prevent="clear"
      />
      <kbd class="shrink-0 whitespace-nowrap rounded border border-line-strong px-1.5 py-px font-mono text-xs text-fg-subtle">Ctrl K</kbd>
    </div>

    <div v-if="query.trim() && (searched || error)" class="flex max-h-80 flex-col gap-0.5 overflow-y-auto rounded-lg border border-line bg-card p-1" role="list" aria-label="Resultados da busca">
      <p v-if="error" role="alert" class="m-0 px-2 py-2 text-xs text-diff-del-fg">{{ error }}</p>
      <p v-else-if="results.length === 0" class="m-0 px-2 py-2 text-xs text-fg-muted">Nenhuma sessão encontrada</p>
      <button
        v-for="session in results"
        :key="session.session_id"
        type="button"
        role="listitem"
        data-test="search-result"
        class="flex min-h-11 w-full cursor-pointer flex-col gap-0.5 rounded-md border-none bg-transparent px-2 py-1.5 text-left text-fg hover:bg-elevated focus-visible:outline-2 focus-visible:outline-primary"
        @click="open(session)"
      >
        <span class="w-full truncate text-[13px] font-medium">{{ session.title }}</span>
        <span class="flex w-full items-center gap-1.5 text-xs text-fg-muted">
          <span
            class="size-2 shrink-0 rounded-[2px]"
            :style="{ backgroundColor: projects.byId(session.project_id)?.color }"
            aria-hidden="true"
          />
          <span class="min-w-0 truncate">{{ projects.byId(session.project_id)?.name ?? 'Projeto removido' }}</span>
          <span aria-hidden="true">·</span>
          <DisplayStateIcon :display="session.display_state" :size="11" :quiet="!needsYou(session)" />
          <span class="shrink-0">{{ displayStateLabel(session) }}</span>
          <span class="grow" />
          <span class="shrink-0 font-mono">{{ formatActivity(session.last_activity_at) }}</span>
        </span>
      </button>
    </div>
  </div>
</template>
