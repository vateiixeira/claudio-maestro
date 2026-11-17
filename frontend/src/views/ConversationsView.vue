<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ConversationRow from '../components/conversation/ConversationRow.vue'
import { errorMessage } from '../api/http'
import DisplayStateIcon from '../components/DisplayStateIcon.vue'
import LoadStatus from '../components/LoadStatus.vue'
import FilterChip from '../components/ui/FilterChip.vue'
import { groupByDate, matchesConversationsState, type ConversationsState } from '../conversationList'
import { isDiscarded } from '../conversation/marks'
import { sortGroups } from '../groupList'
import { useLoadState } from '../loadState'
import { useGitStore } from '../stores/git'
import { useGroupsStore } from '../stores/groups'
import { useNewConversationStore } from '../stores/newConversation'
import { useProjectsStore } from '../stores/projects'
import { useSessionsStore } from '../stores/sessions'
import IconPlus from '../components/icons/IconPlus.vue'

const PAGE = 100
const STATES: ConversationsState[] = ['todas', 'em-execucao', 'sua-vez', 'nao-lidas', 'finalizadas', 'ativas', 'em-espera', 'bloqueadas', 'para-revisar', 'prioridade', 'descartadas']
// The states with a chip. The rest sit in the "Mais filtros" select.
const CHIPS: { id: ConversationsState; label: string; counted: boolean }[] = [
  { id: 'todas', label: 'Todas', counted: false },
  { id: 'em-execucao', label: 'Em execução', counted: true },
  { id: 'sua-vez', label: 'Sua vez', counted: true },
  { id: 'nao-lidas', label: 'Não lidas', counted: true },
  { id: 'finalizadas', label: 'Finalizadas', counted: false },
]
const MORE_FILTERS: { id: ConversationsState; label: string }[] = [
  { id: 'ativas', label: 'Ativas' },
  { id: 'em-espera', label: 'Em espera' },
  { id: 'bloqueadas', label: 'Bloqueadas' },
  { id: 'para-revisar', label: 'Para revisar' },
  { id: 'prioridade', label: 'Prioridade' },
  { id: 'descartadas', label: 'Descartadas' },
]
const SELECT = 'h-[1.875rem] rounded-full border border-line-strong bg-elevated px-3 text-[0.78125rem] text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary'

const route = useRoute()
const router = useRouter()
const sessions = useSessionsStore()
const projects = useProjectsStore()
const git = useGitStore()
const groupStore = useGroupsStore()
const loadState = useLoadState()
const newConversation = useNewConversationStore()

const text = (v: unknown) => (typeof v === 'string' ? v : '')
const state = computed<ConversationsState>(() => {
  const v = text(route.query.estado) as ConversationsState
  return STATES.includes(v) ? v : 'todas'
})
// The select shows "Mais filtros" (empty) while a chip, or no state at all, is the one in use.
const moreFilter = computed(() => (MORE_FILTERS.some((f) => f.id === state.value) ? state.value : ''))
const projectId = computed(() => text(route.query.projeto))
const search = computed(() => text(route.query.busca))
// Chained so two quick changes each start from the query the previous one left.
// A failed navigation is swallowed so it neither blocks later changes nor goes unhandled.
let navigation: Promise<unknown> = Promise.resolve()
function setQuery(key: string, value: string) {
  navigation = navigation
    .then(() => router.replace({ query: { ...route.query, [key]: value || undefined } }))
    .catch(() => {})
}

const projectGroups = computed(() => {
  if (!projectId.value) return []
  return sortGroups(groupStore.visibleIn(Number(projectId.value), sessions.all), sessions.all)
})
// '' = all, 'sem' = loose ones, else a group shown in the chosen project (any other id counts as '').
const groupFilter = computed(() => {
  const v = text(route.query.agrupador)
  if (v === 'sem') return v
  return projectGroups.value.some((g) => String(g.id) === v) ? v : ''
})

// Changing the project also drops the group filter, since the visible groups change with the project.
function setProject(value: string) {
  navigation = navigation
    .then(() => router.replace({ query: { ...route.query, projeto: value || undefined, agrupador: undefined } }))
    .catch(() => {})
}

const error = ref<string | null>(null)
async function discard(sessionId: string) {
  try {
    await sessions.setMark(sessionId, 'discarded')
  } catch (e) {
    error.value = errorMessage(e)
  }
}
const limit = ref(PAGE)
watch(() => route.query, () => { limit.value = PAGE })

// The project and group in force, before the state and the search: the scope the chip counts are taken in.
const inScope = computed(() => sessions.all.filter((s) => {
  if (projectId.value && s.project_id !== Number(projectId.value)) return false
  if (groupFilter.value === 'sem' && s.group_id != null) return false
  if (groupFilter.value && groupFilter.value !== 'sem' && String(s.group_id) !== groupFilter.value) return false
  return true
}))
const counts = computed(() => Object.fromEntries(
  CHIPS.filter((c) => c.counted).map((c) => [c.id, inScope.value.filter((s) => matchesConversationsState(s, c.id)).length]),
))
const filtered = computed(() => {
  const q = search.value.trim().toLocaleLowerCase('pt-BR')
  return inScope.value.filter((s) => {
    if (!matchesConversationsState(s, state.value)) return false
    if (!q) return true
    const groupName = s.group_id != null ? groupStore.byId(s.group_id)?.name ?? '' : ''
    return s.title.toLocaleLowerCase('pt-BR').includes(q) || groupName.toLocaleLowerCase('pt-BR').includes(q)
  })
})
const dateGroups = computed(() => groupByDate(filtered.value.slice(0, limit.value), new Date(), true))
watch(() => projects.projects.map((p) => p.id), (ids) => ids.forEach((id) => git.ensure(id)), { immediate: true })
</script>

<template>
  <div class="mx-auto flex w-full max-w-5xl flex-col gap-4 px-6 py-6">
    <div class="flex flex-wrap items-center gap-3">
      <h1 class="m-0 text-[1.625rem] leading-tight font-semibold tracking-tight text-fg">Conversas</h1>
      <span class="grow" />
      <input :value="search" data-test="conversations-search" type="search" placeholder="Buscar conversas…" aria-label="Buscar conversas" class="h-9 w-64 rounded-md border border-line-strong bg-elevated px-3 text-sm text-fg outline-none focus:border-fg-muted" @input="setQuery('busca', ($event.target as HTMLInputElement).value)" />
      <button type="button" data-test="conversations-new" aria-keyshortcuts="C" class="flex h-9 items-center gap-1.5 rounded-md border border-line-strong px-3 text-sm font-medium text-fg hover:bg-card focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary" @click="newConversation.open(projectId ? Number(projectId) : null)"><IconPlus :size="14" />Nova conversa<kbd aria-hidden="true" class="rounded-sm border border-line-strong px-1.5 py-px font-mono text-[0.6875rem] font-normal text-fg-muted max-sm:hidden">C</kbd></button>
    </div>
    <div class="flex flex-wrap items-center gap-2">
      <div role="group" aria-label="Filtrar por estado" class="flex flex-wrap items-center gap-2">
        <FilterChip
          v-for="c in CHIPS" :key="c.id" data-test="conversations-chip" :data-state="c.id"
          :label="c.label" :count="c.counted ? counts[c.id] : undefined" :pressed="state === c.id"
          @toggle="setQuery('estado', c.id === 'todas' ? '' : c.id)"
        >
          <template v-if="c.id === 'em-execucao'" #icon><DisplayStateIcon display="running" :quiet="counts['em-execucao'] === 0" /></template>
          <template v-else-if="c.id === 'sua-vez'" #icon><DisplayStateIcon display="waiting" /></template>
          <template v-else-if="c.id === 'nao-lidas'" #icon><span class="size-[0.4375rem] shrink-0 rounded-full bg-fg" aria-hidden="true" /></template>
          <template v-else-if="c.id === 'finalizadas'" #icon><DisplayStateIcon display="finished" /></template>
        </FilterChip>
      </div>
      <span class="grow" />
      <select :value="moreFilter" data-test="conversations-state" aria-label="Mais filtros" :class="SELECT" @change="setQuery('estado', ($event.target as HTMLSelectElement).value)">
        <option value="">Mais filtros</option>
        <option v-for="f in MORE_FILTERS" :key="f.id" :value="f.id">{{ f.label }}</option>
      </select>
      <select :value="projectId" data-test="conversations-project" aria-label="Projeto" :class="SELECT" @change="setProject(($event.target as HTMLSelectElement).value)">
        <option value="">Todos os projetos</option>
        <option v-for="p in projects.projects" :key="p.id" :value="String(p.id)">{{ p.name }}</option>
      </select>
      <select v-if="projectGroups.length" :value="groupFilter" data-test="conversations-group" aria-label="Agrupador" :class="SELECT" @change="setQuery('agrupador', ($event.target as HTMLSelectElement).value)">
        <option value="">Todos os agrupadores</option>
        <option value="sem">Sem agrupador</option>
        <option v-for="g in projectGroups" :key="g.id" :value="String(g.id)">{{ g.name }}</option>
      </select>
    </div>
    <p v-if="error" role="alert" class="m-0 text-sm text-diff-del-fg">{{ error }}</p>
    <LoadStatus v-if="loadState !== 'ready'" :state="loadState" />
    <p v-else-if="dateGroups.length === 0" data-test="empty" class="m-0 py-10 text-center text-fg-muted">Nenhuma conversa aqui.</p>
    <template v-else>
      <section v-for="group in dateGroups" :key="group.label" :aria-label="group.label" class="flex flex-col">
        <!-- Same grid as ConversationRow, so the captions sit over their columns. Below md only the group name stays. -->
        <div
          data-test="conversations-columns"
          class="grid h-7 grid-cols-1 items-center gap-x-4 border-b border-line-strong px-2.5 font-mono text-[0.6875rem] tracking-[0.08em] text-fg-subtle uppercase xl:grid-cols-[0.875rem_minmax(0,1fr)_11rem_10.5rem_4.25rem]"
        >
          <span class="max-xl:hidden" />
          <span data-test="date-group">{{ group.label }}</span>
          <span class="max-xl:hidden">Situação</span>
          <span class="max-xl:hidden">Projeto</span>
          <span class="text-right max-xl:hidden">Atividade</span>
        </div>
        <ConversationRow v-for="s in group.sessions" :key="s.session_id" :session="s" @error="error = $event">
          <template v-if="!isDiscarded(s)" #actions>
            <button type="button" data-test="row-discard" class="h-8 rounded-md px-2 text-xs text-fg-muted hover:bg-elevated hover:text-fg disabled:opacity-40" :aria-label="`Descartar ${s.title}`" @click="discard(s.session_id)">Descartar</button>
          </template>
        </ConversationRow>
      </section>
    </template>
    <button v-if="loadState === 'ready' && filtered.length > limit" type="button" data-test="show-more" class="h-10 self-center rounded-md border border-line-strong px-4 text-sm text-fg hover:bg-card" @click="limit += PAGE">Mostrar mais</button>
  </div>
</template>
