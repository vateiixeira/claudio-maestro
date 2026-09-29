<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ConversationRow from '../components/conversation/ConversationRow.vue'
import { groupByDate } from '../conversationList'
import { useGitStore } from '../stores/git'
import { useNewConversationStore } from '../stores/newConversation'
import { useProjectsStore } from '../stores/projects'
import { useSessionsStore } from '../stores/sessions'

const PAGE = 100
type StateFilter = 'ativas' | 'finalizadas' | 'todas'

const route = useRoute()
const router = useRouter()
const sessions = useSessionsStore()
const projects = useProjectsStore()
const git = useGitStore()
const newConversation = useNewConversationStore()

const text = (v: unknown) => (typeof v === 'string' ? v : '')
const state = computed<StateFilter>(() => {
  const v = text(route.query.estado)
  return v === 'ativas' || v === 'finalizadas' ? v : 'todas'
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

const error = ref<string | null>(null)
const limit = ref(PAGE)
watch(() => route.query, () => { limit.value = PAGE })

const filtered = computed(() => {
  const q = search.value.trim().toLocaleLowerCase('pt-BR')
  return sessions.all.filter((s) => {
    if (state.value === 'ativas' && s.display_state === 'finished') return false
    if (state.value === 'finalizadas' && s.display_state !== 'finished') return false
    if (projectId.value && s.project_id !== Number(projectId.value)) return false
    return !q || s.title.toLocaleLowerCase('pt-BR').includes(q)
  })
})
const groups = computed(() => groupByDate(filtered.value.slice(0, limit.value), new Date(), true))
watch(() => projects.projects.map((p) => p.id), (ids) => ids.forEach((id) => git.ensure(id)), { immediate: true })
</script>

<template>
  <div class="mx-auto flex w-full max-w-5xl flex-col gap-4 px-6 py-6">
    <h1 class="m-0 font-mono text-sm tracking-[0.08em] text-fg uppercase">Conversas</h1>
    <div class="flex flex-wrap items-center gap-3">
      <button type="button" data-test="conversations-new" class="h-9 rounded-md border border-line-strong px-3 text-sm font-medium text-fg hover:bg-card" @click="newConversation.open(projectId ? Number(projectId) : null)">＋ Nova conversa</button>
      <input :value="search" data-test="conversations-search" type="search" placeholder="Buscar conversas…" aria-label="Buscar conversas" class="h-9 w-64 rounded-md border border-line-strong bg-bg px-3 text-sm text-fg outline-none focus:border-primary" @input="setQuery('busca', ($event.target as HTMLInputElement).value)" />
      <span class="grow" />
      <select :value="projectId" data-test="conversations-project" aria-label="Projeto" class="h-9 rounded-md border border-line-strong bg-bg px-2 text-sm text-fg" @change="setQuery('projeto', ($event.target as HTMLSelectElement).value)">
        <option value="">Todos os projetos</option>
        <option v-for="p in projects.projects" :key="p.id" :value="String(p.id)">{{ p.name }}</option>
      </select>
      <select :value="state" data-test="conversations-state" aria-label="Estado" class="h-9 rounded-md border border-line-strong bg-bg px-2 text-sm text-fg" @change="setQuery('estado', ($event.target as HTMLSelectElement).value)">
        <option value="todas">Todas</option>
        <option value="ativas">Ativas</option>
        <option value="finalizadas">Finalizadas</option>
      </select>
    </div>
    <p v-if="error" role="alert" class="m-0 text-sm text-secondary-soft">{{ error }}</p>
    <p v-if="groups.length === 0" data-test="empty" class="m-0 py-10 text-center text-fg-muted">Nenhuma conversa aqui.</p>
    <section v-for="group in groups" :key="group.label" :aria-label="group.label" class="flex flex-col">
      <div class="flex items-center gap-3 py-2">
        <span class="h-px grow bg-line" /><span data-test="date-group" class="font-mono text-[11px] tracking-[0.08em] text-fg-muted uppercase">{{ group.label }}</span><span class="h-px grow bg-line" />
      </div>
      <ConversationRow v-for="s in group.sessions" :key="s.session_id" :session="s" @error="error = $event" />
    </section>
    <button v-if="filtered.length > limit" type="button" data-test="show-more" class="h-10 self-center rounded-md border border-line-strong px-4 text-sm text-fg hover:bg-card" @click="limit += PAGE">Mostrar mais</button>
  </div>
</template>
