<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ConversationRow from '../components/conversation/ConversationRow.vue'
import { errorMessage } from '../api/http'
import LoadStatus from '../components/LoadStatus.vue'
import { groupByDate } from '../conversationList'
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
type StateFilter = 'ativas' | 'finalizadas' | 'em-espera' | 'bloqueadas' | 'para-revisar' | 'prioridade' | 'descartadas' | 'todas'
const STATE_FILTERS: StateFilter[] = ['ativas', 'finalizadas', 'em-espera', 'bloqueadas', 'para-revisar', 'prioridade', 'descartadas']
const MARK_OF: Partial<Record<StateFilter, string>> = { 'em-espera': 'on_hold', bloqueadas: 'blocked', 'para-revisar': 'review', descartadas: 'discarded' }

const route = useRoute()
const router = useRouter()
const sessions = useSessionsStore()
const projects = useProjectsStore()
const git = useGitStore()
const groupStore = useGroupsStore()
const loadState = useLoadState()
const newConversation = useNewConversationStore()

const text = (v: unknown) => (typeof v === 'string' ? v : '')
const state = computed<StateFilter>(() => {
  const v = text(route.query.estado) as StateFilter
  return STATE_FILTERS.includes(v) ? v : 'todas'
})
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
  const id = Number(projectId.value)
  return sortGroups(groupStore.forProject(id), sessions.forProject(id))
})
// '' = all, 'sem' = loose ones, else a group of the chosen project (any other id counts as '').
const groupFilter = computed(() => {
  const v = text(route.query.agrupador)
  if (v === 'sem') return v
  return projectGroups.value.some((g) => String(g.id) === v) ? v : ''
})

// Changing the project also drops the group filter, since its ids belong to the old project.
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

const filtered = computed(() => {
  const q = search.value.trim().toLocaleLowerCase('pt-BR')
  return sessions.all.filter((s) => {
    if (state.value !== 'descartadas' && isDiscarded(s)) return false
    if (state.value === 'ativas' && s.display_state === 'finished') return false
    if (state.value === 'finalizadas' && s.display_state !== 'finished') return false
    const mark = MARK_OF[state.value]
    if (mark && s.mark !== mark) return false
    if (state.value === 'prioridade' && !s.priority) return false
    if (projectId.value && s.project_id !== Number(projectId.value)) return false
    if (groupFilter.value === 'sem' && s.group_id != null) return false
    if (groupFilter.value && groupFilter.value !== 'sem' && String(s.group_id) !== groupFilter.value) return false
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
    <h1 class="m-0 font-mono text-sm tracking-[0.08em] text-fg uppercase">Conversas</h1>
    <div class="flex flex-wrap items-center gap-3">
      <button type="button" data-test="conversations-new" class="flex h-9 items-center gap-1.5 rounded-md border border-line-strong px-3 text-sm font-medium text-fg hover:bg-card" @click="newConversation.open(projectId ? Number(projectId) : null)"><IconPlus :size="14" />Nova conversa</button>
      <input :value="search" data-test="conversations-search" type="search" placeholder="Buscar conversas…" aria-label="Buscar conversas" class="h-9 w-64 rounded-md border border-line-strong bg-elevated px-3 text-sm text-fg outline-none focus:border-fg-muted" @input="setQuery('busca', ($event.target as HTMLInputElement).value)" />
      <span class="grow" />
      <select :value="projectId" data-test="conversations-project" aria-label="Projeto" class="h-9 rounded-md border border-line-strong bg-elevated px-2 text-sm text-fg" @change="setProject(($event.target as HTMLSelectElement).value)">
        <option value="">Todos os projetos</option>
        <option v-for="p in projects.projects" :key="p.id" :value="String(p.id)">{{ p.name }}</option>
      </select>
      <select v-if="projectGroups.length" :value="groupFilter" data-test="conversations-group" aria-label="Agrupador" class="h-9 rounded-md border border-line-strong bg-elevated px-2 text-sm text-fg" @change="setQuery('agrupador', ($event.target as HTMLSelectElement).value)">
        <option value="">Todos os agrupadores</option>
        <option value="sem">Sem agrupador</option>
        <option v-for="g in projectGroups" :key="g.id" :value="String(g.id)">{{ g.name }}</option>
      </select>
      <select :value="state" data-test="conversations-state" aria-label="Estado" class="h-9 rounded-md border border-line-strong bg-elevated px-2 text-sm text-fg" @change="setQuery('estado', ($event.target as HTMLSelectElement).value)">
        <option value="todas">Todas</option>
        <option value="ativas">Ativas</option>
        <option value="finalizadas">Finalizadas</option>
        <option value="em-espera">Em espera</option>
        <option value="bloqueadas">Bloqueadas</option>
        <option value="para-revisar">Para revisar</option>
        <option value="prioridade">Prioridade</option>
        <option value="descartadas">Descartadas</option>
      </select>
    </div>
    <p v-if="error" role="alert" class="m-0 text-sm text-diff-del-fg">{{ error }}</p>
    <LoadStatus v-if="loadState !== 'ready'" :state="loadState" />
    <p v-else-if="dateGroups.length === 0" data-test="empty" class="m-0 py-10 text-center text-fg-muted">Nenhuma conversa aqui.</p>
    <template v-else>
      <section v-for="group in dateGroups" :key="group.label" :aria-label="group.label" class="flex flex-col">
        <div class="flex items-center gap-3 py-2">
          <span class="h-px grow bg-line" /><span data-test="date-group" class="font-mono text-[0.6875rem] tracking-[0.08em] text-fg-subtle uppercase">{{ group.label }}</span><span class="h-px grow bg-line" />
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
