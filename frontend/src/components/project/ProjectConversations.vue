<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import type { RouteLocationRaw } from 'vue-router'
import ConversationRow from '../conversation/ConversationRow.vue'
import GroupRemoveConfirm from '../groups/GroupRemoveConfirm.vue'
import IconPlus from '../icons/IconPlus.vue'
import { errorMessage } from '../../api/http'
import { isDiscarded } from '../../conversation/marks'
import { needsYou } from '../../conversation/needsYou'
import { groupOptionLabel, sortGroups } from '../../groupList'
import { useGroupsStore } from '../../stores/groups'
import { useNewConversationStore } from '../../stores/newConversation'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import type { Session } from '../../types/api'

const props = withDefaults(defineProps<{
  projectId: number
  available: boolean
  rowTarget?: (sessionId: string) => RouteLocationRaw | undefined
  activeId?: string | null
  loading?: boolean
  loadError?: string | null
}>(), { loading: false, loadError: null })
const emit = defineEmits<{ error: [message: string]; retry: [] }>()
const sessions = useSessionsStore()
const groups = useGroupsStore()
const projects = useProjectsStore()
const newConversation = useNewConversationStore()
const query = ref('')
const groupFilter = ref('all')
const stateFilter = ref<'open' | 'finished' | 'all'>('open')
const allSessions = computed(() => sessions.all.filter(session => !isDiscarded(session)))
const visibleGroups = computed(() => sortGroups(groups.visibleIn(props.projectId, allSessions.value), allSessions.value))
const groupIds = computed(() => new Set(visibleGroups.value.map(group => group.id)))
const selectedGroup = computed(() => visibleGroups.value.find(group => String(group.id) === groupFilter.value))
const groupSessions = computed(() => allSessions.value.filter(session => session.group_id === selectedGroup.value?.id))
const normalize = (value: string) => value.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLocaleLowerCase('pt-BR')
const matching = computed(() => {
  const unique = new Map<string, Session>()
  const term = normalize(query.value.trim())
  for (const session of allSessions.value) {
    const belongs = session.project_id === props.projectId || (session.group_id != null && groupIds.value.has(session.group_id))
    if (!belongs) continue
    if (groupFilter.value === 'none' && (session.project_id !== props.projectId || (session.group_id != null && groupIds.value.has(session.group_id)))) continue
    if (selectedGroup.value && session.group_id !== selectedGroup.value.id) continue
    if (term && !normalize(`${session.title} ${session.digest_short ?? ''}`).includes(term)) continue
    unique.set(session.session_id, session)
  }
  return [...unique.values()].sort((a, b) => b.last_activity_at - a.last_activity_at || b.created_at - a.created_at || a.session_id.localeCompare(b.session_id))
})
const openCount = computed(() => matching.value.filter(session => session.display_state !== 'finished').length)
const filtered = computed(() => matching.value.filter(session => stateFilter.value === 'all' || (session.display_state === 'finished') === (stateFilter.value === 'finished')))
const sections = computed(() => {
  const buckets: Record<'needs' | 'running' | 'recent', Session[]> = { needs: [], running: [], recent: [] }
  for (const session of filtered.value) {
    const bucket = session.display_state === 'finished' ? 'recent' : needsYou(session) ? 'needs' : session.display_state === 'running' ? 'running' : 'recent'
    buckets[bucket].push(session)
  }
  return [
    { id: 'needs', title: 'Precisam de você', sessions: buckets.needs },
    { id: 'running', title: 'Em andamento', sessions: buckets.running },
    { id: 'recent', title: 'Recentes', sessions: buckets.recent },
  ].filter(section => section.sessions.length)
})
const emptyText = computed(() => {
  if (query.value.trim()) return 'Nenhuma conversa corresponde à busca.'
  if (stateFilter.value === 'finished') return 'Nenhuma conversa finalizada neste filtro.'
  if (stateFilter.value === 'open') return 'Nenhuma conversa em aberto neste filtro.'
  return 'Nenhuma conversa neste filtro.'
})

const editing = ref<'create' | 'rename' | null>(null)
const name = ref('')
const nameInput = ref<HTMLInputElement | null>(null)
const groupSelect = ref<HTMLSelectElement | null>(null)
const createButton = ref<HTMLButtonElement | null>(null)
const renameButton = ref<HTMLButtonElement | null>(null)
const editError = ref<string | null>(null)
const busy = ref(false)
const confirming = ref(false)
const removeButton = ref<HTMLButtonElement | null>(null)
let generation = 0
function resetEditing() {
  generation++
  editing.value = null
  confirming.value = false
  editError.value = null
  busy.value = false
}
watch(() => props.projectId, () => {
  resetEditing()
  query.value = ''
  groupFilter.value = 'all'
  stateFilter.value = 'open'
})
watch(groupFilter, resetEditing)
watch(visibleGroups, () => {
  if (!['all', 'none'].includes(groupFilter.value) && !selectedGroup.value) groupFilter.value = 'all'
})
onBeforeUnmount(() => { generation++ })
async function startEdit(mode: 'create' | 'rename') {
  resetEditing()
  editing.value = mode
  name.value = mode === 'rename' ? selectedGroup.value?.name ?? '' : ''
  await nextTick()
  nameInput.value?.focus()
  if (mode === 'rename') nameInput.value?.select()
}
async function cancelEdit() {
  const mode = editing.value
  resetEditing()
  await nextTick()
  if (mode === 'rename') renameButton.value?.focus()
  else createButton.value?.focus()
}
async function saveGroup() {
  if (busy.value || !name.value.trim() || !editing.value) return
  const mine = generation
  const projectId = props.projectId
  const groupId = selectedGroup.value?.id
  const mode = editing.value
  if (mode === 'rename' && groupId === undefined) return
  busy.value = true
  editError.value = null
  try {
    const group = mode === 'create' ? await groups.create(projectId, name.value.trim()) : await groups.rename(groupId!, name.value.trim())
    if (mine !== generation) return
    editing.value = null
    groupFilter.value = String(group.id)
    await nextTick()
    if (props.projectId === projectId && groupFilter.value === String(group.id)) groupSelect.value?.focus()
  } catch (error) {
    if (mine !== generation) return
    editError.value = errorMessage(error)
  } finally {
    if (mine === generation) busy.value = false
  }
}
async function cancelRemove() {
  confirming.value = false
  await nextTick()
  removeButton.value?.focus()
}
async function removed() {
  confirming.value = false
  groupFilter.value = 'all'
  await nextTick()
  groupSelect.value?.focus()
}
function removeError(message: string) {
  editError.value = message
}
const control = 'min-h-9 rounded-md border border-line-strong bg-elevated px-3 text-sm text-fg outline-none focus-visible:ring-2 focus-visible:ring-primary'
</script>

<template>
  <section data-test="project-conversations" aria-label="Conversas do projeto" class="flex min-w-0 flex-col gap-5">
    <div class="flex min-w-0 flex-wrap items-center gap-2">
      <input v-model="query" data-test="conversation-search" type="search" aria-label="Buscar nas conversas do projeto" placeholder="Buscar neste projeto" :class="control" class="min-w-0 flex-[1_1_15rem]" />
      <select ref="groupSelect" v-model="groupFilter" data-test="conversation-group-filter" aria-label="Agrupador" :class="control" class="min-w-0 max-w-full flex-[1_1_12rem] sm:max-w-64">
        <option value="all">Agrupador: Todos</option>
        <option value="none">Sem agrupador</option>
        <option v-for="group in visibleGroups" :key="group.id" :value="String(group.id)">{{ groupOptionLabel(group, projectId, projects.projects) }}</option>
      </select>
      <div role="group" aria-label="Estado das conversas" class="flex min-w-0 flex-wrap gap-1 rounded-md border border-line-strong p-0.5">
        <button v-for="filter in (['open', 'finished', 'all'] as const)" :key="filter" type="button" :data-test="`filter-${filter}`" :aria-pressed="stateFilter === filter" class="min-h-8 rounded px-2.5 text-xs font-medium focus-visible:outline-2 focus-visible:outline-primary" :class="stateFilter === filter ? 'bg-primary/10 text-primary-soft' : 'text-fg-muted hover:bg-card hover:text-fg'" @click="stateFilter = filter">
          {{ filter === 'open' ? 'Em aberto' : filter === 'finished' ? 'Finalizadas' : 'Todas' }}<span v-if="filter === 'open'" class="ml-1.5 font-mono text-fg-subtle">{{ openCount }}</span>
        </button>
      </div>
    </div>

    <div v-if="selectedGroup" data-test="selected-group-actions" class="flex min-w-0 flex-wrap items-center gap-1 text-xs">
      <span class="mr-auto min-w-0 truncate font-semibold text-fg-muted">{{ selectedGroup.name }}</span>
      <button type="button" data-test="group-new-session" :disabled="!available" class="min-h-9 rounded-md px-2 text-primary-soft hover:bg-card disabled:opacity-40" @click="newConversation.open(projectId, selectedGroup.id)">Nova conversa no agrupador</button>
      <button ref="renameButton" type="button" data-test="group-rename" class="min-h-9 rounded-md px-2 text-fg-muted hover:bg-card hover:text-fg" @click="startEdit('rename')">Renomear</button>
      <button ref="removeButton" type="button" data-test="group-remove" class="min-h-9 rounded-md px-2 text-fg-muted hover:bg-card hover:text-fg" @click="resetEditing(); confirming = true">Remover</button>
    </div>
    <form v-if="editing" data-test="group-name-form" class="flex flex-wrap gap-2" @submit.prevent="saveGroup" @keydown.esc.prevent="cancelEdit">
      <label :for="`project-${projectId}-group-name`" class="sr-only">{{ editing === 'create' ? 'Nome do agrupador' : 'Novo nome do agrupador' }}</label>
      <input :id="`project-${projectId}-group-name`" ref="nameInput" v-model="name" data-test="group-name-input" maxlength="80" :disabled="busy" :class="control" class="min-w-0 flex-[1_1_12rem]" placeholder="Nome do agrupador" />
      <button type="submit" data-test="group-save" :disabled="busy || !name.trim()" class="min-h-9 rounded-md bg-primary px-3 text-sm font-semibold text-primary-fg hover:bg-primary-soft disabled:opacity-40">{{ busy ? 'Salvando…' : 'Salvar' }}</button>
      <button type="button" class="min-h-9 rounded-md px-3 text-sm text-fg-muted hover:bg-card" @click="cancelEdit">Cancelar</button>
    </form>
    <p v-if="editError" role="alert" class="m-0 text-sm text-diff-del-fg">{{ editError }}</p>
    <GroupRemoveConfirm v-if="confirming && selectedGroup" :key="`${projectId}:${selectedGroup.id}`" :group="selectedGroup" :sessions="groupSessions" @removed="removed" @cancel="cancelRemove" @error="removeError" />

    <div v-if="loadError" role="alert" class="flex flex-wrap items-center gap-2 text-sm text-diff-del-fg">
      <span>{{ loadError }}</span>
      <button type="button" data-test="conversations-retry" :disabled="loading" class="min-h-9 rounded-md px-2 underline hover:bg-card disabled:opacity-40" @click="emit('retry')">Tentar novamente</button>
    </div>
    <p v-if="loading" data-test="conversations-loading" role="status" class="m-0 text-sm text-fg-muted">Carregando conversas…</p>
    <section v-for="section in sections" :key="section.id" data-test="conversation-section" :data-section="section.id" :aria-labelledby="`conversations-${projectId}-${section.id}`" class="min-w-0">
      <h2 :id="`conversations-${projectId}-${section.id}`" data-test="conversation-section-title" class="m-0 mb-2 border-b border-line pb-2 text-xs font-semibold tracking-wide text-fg-muted">{{ section.title }}</h2>
      <ConversationRow v-for="session in section.sessions" :key="session.session_id" :session="session" :project-context-id="projectId" :to="rowTarget?.(session.session_id)" :active="activeId === session.session_id" @error="emit('error', $event)" />
    </section>
    <p v-if="!loading && !loadError && !filtered.length" data-test="conversations-empty" class="m-0 py-5 text-sm text-fg-muted">{{ emptyText }}</p>
    <button v-if="!editing" ref="createButton" type="button" data-test="group-new" class="flex min-h-9 self-start items-center gap-1.5 rounded-md px-2 text-sm text-primary-soft hover:bg-card" @click="startEdit('create')"><IconPlus :size="14" />Criar agrupador</button>
  </section>
</template>
