<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ConversationRow from '../components/conversation/ConversationRow.vue'
import FirstSteps from '../components/FirstSteps.vue'
import InboxTriageRow from '../components/inbox/InboxTriageRow.vue'
import LoadStatus from '../components/LoadStatus.vue'
import { errorMessage, markSessionsSeen } from '../api/http'
import { isBareShortcut } from '../keyboardShortcutGuard'
import { useLoadState } from '../loadState'
import { INBOX_TABS, groupByDate, inInbox, isInboxTab, type InboxTab } from '../conversationList'
import { useGitStore } from '../stores/git'
import { useProjectsStore } from '../stores/projects'
import { useSessionsStore } from '../stores/sessions'

const route = useRoute()
const router = useRouter()
const sessions = useSessionsStore()
const projects = useProjectsStore()
const git = useGitStore()
const loadState = useLoadState()

const tab = computed<InboxTab>(() => (isInboxTab(route.query.aba) ? route.query.aba : 'pede-voce'))
function selectTab(id: InboxTab) {
  void router.replace({ query: { ...route.query, aba: id } })
}

const search = ref('')
const projectFilter = ref('')
const error = ref<string | null>(null)
const marking = ref(false)

const visible = computed(() => {
  const q = search.value.trim().toLocaleLowerCase('pt-BR')
  return sessions.all.filter((s) =>
    inInbox(s, tab.value)
    && (!projectFilter.value || s.project_id === Number(projectFilter.value))
    && (!q || s.title.toLocaleLowerCase('pt-BR').includes(q)),
  )
})
const groups = computed(() => groupByDate(visible.value, new Date(), false))
watch(() => projects.projects.map((p) => p.id), (ids) => ids.forEach((id) => git.ensure(id)), { immediate: true })

// Keyboard triage of "Aguardando você": a listbox with a cursor (`focusedId`) that j/k and the arrows move.
// Nothing is under the cursor until the first move, so a stray `a` never answers a row nobody looked at.
const triage = computed(() => tab.value === 'pede-voce')
const flat = computed(() => groups.value.flatMap((g) => g.sessions))
const focusedId = ref<string | null>(null)
const listEl = ref<HTMLElement | null>(null)
const rowRefs = new Map<string, InstanceType<typeof InboxTriageRow>>()
const announcement = ref('')
const kbdClass = 'rounded-sm border border-line-strong px-1.5 py-0.5 font-mono text-[0.6875rem] text-fg-muted'
let focusedIndex = -1

function setRow(id: string, el: unknown) {
  if (el) rowRefs.set(id, el as InstanceType<typeof InboxTriageRow>)
  else rowRefs.delete(id)
}

function focusRow(id: string | null) {
  focusedId.value = id
  if (!id) return
  void nextTick(() => document.getElementById(`inbox-option-${id}`)?.scrollIntoView?.({ block: 'nearest' }))
}

function move(step: 1 | -1) {
  const rows = flat.value
  if (!rows.length) return
  if (listEl.value && !listEl.value.contains(document.activeElement)) listEl.value.focus({ preventScroll: true })
  const current = focusedId.value ? rows.findIndex((s) => s.session_id === focusedId.value) : -1
  const next = current === -1 ? 0 : Math.min(rows.length - 1, Math.max(0, current + step))
  focusRow(rows[next]!.session_id)
}

// The row under the cursor left the list (answered, marked, filtered): the cursor stays at the same place.
watch(flat, (rows) => {
  if (!focusedId.value) return
  const index = rows.findIndex((s) => s.session_id === focusedId.value)
  if (index !== -1) focusedIndex = index
  else focusRow(rows.length ? rows[Math.min(Math.max(focusedIndex, 0), rows.length - 1)]!.session_id : null)
})
watch(focusedId, (id) => { focusedIndex = id ? flat.value.findIndex((s) => s.session_id === id) : -1 })

async function decideFocused(choice: 'allow_once' | 'deny') {
  const session = flat.value.find((s) => s.session_id === focusedId.value)
  if (!session) return
  if (session.pending_kind === 'question' || session.pending_kind === 'plan') {
    announcement.value = `${session.pending_kind === 'question' ? 'Pergunta' : 'Plano'} em ${session.title}: abra a conversa para responder.`
    return
  }
  const row = rowRefs.get(session.session_id)
  if (!row || !(await row.decide(choice))) return
  announcement.value = `${choice === 'allow_once' ? 'Permitido uma vez' : 'Negado'}: ${session.title}`
  const rows = flat.value
  const at = rows.findIndex((s) => s.session_id === session.session_id)
  if (at !== -1 && at < rows.length - 1) focusRow(rows[at + 1]!.session_id)
}

// The arrows scroll the page, so they only move the cursor while the focus is in the list.
const inList = (event: KeyboardEvent) => event.target instanceof Node && !!listEl.value?.contains(event.target)

function onKey(event: KeyboardEvent) {
  if (!triage.value) return
  if (event.key === 'Enter') {
    // Only from the list itself: on a link or a button, Enter already does its own thing.
    if (event.target !== listEl.value || !isBareShortcut(event, 'Enter') || !focusedId.value) return
    event.preventDefault()
    void router.push({ name: 'session', params: { id: focusedId.value } })
  } else if (isBareShortcut(event, 'j') || (inList(event) && isBareShortcut(event, 'ArrowDown'))) {
    event.preventDefault()
    move(1)
  } else if (isBareShortcut(event, 'k') || (inList(event) && isBareShortcut(event, 'ArrowUp'))) {
    event.preventDefault()
    move(-1)
  } else if (!inList(event)) {
    // Deciding needs the list to hold the focus: after a click elsewhere, a stray key must not answer a tool.
    return
  } else if (isBareShortcut(event, 'a')) {
    event.preventDefault()
    void decideFocused('allow_once')
  } else if (isBareShortcut(event, 'd')) {
    event.preventDefault()
    void decideFocused('deny')
  }
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
watch(tab, () => { focusedId.value = null })

async function markAll() {
  const ids = visible.value.filter((s) => s.unread).map((s) => s.session_id)
  if (!ids.length || marking.value) return
  marking.value = true
  error.value = null
  try {
    await markSessionsSeen(ids)
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    marking.value = false
  }
}
</script>

<template>
  <div class="mx-auto flex w-full max-w-5xl flex-col gap-4 px-6 py-6">
    <h1 class="m-0 font-mono text-sm tracking-[0.08em] text-fg uppercase">Inbox</h1>
    <FirstSteps v-if="projects.loaded && !projects.loadError && projects.projects.length === 0" />
    <template v-else>
      <div class="flex flex-wrap items-center gap-3">
        <div role="tablist" aria-label="Filtro da Inbox" class="flex gap-1">
          <button
            v-for="t in INBOX_TABS"
            :key="t.id"
            type="button"
            role="tab"
            data-test="inbox-tab"
            :aria-selected="tab === t.id"
            class="h-9 border-b-2 px-3 text-sm"
            :class="tab === t.id ? 'border-fg text-fg' : 'border-transparent text-fg-muted hover:text-fg'"
            @click="selectTab(t.id)"
          >{{ t.label }}</button>
        </div>
        <span class="grow" />
        <input id="inbox-search" v-model="search" name="inbox-search" data-test="inbox-search" type="search" placeholder="Buscar na Inbox…" aria-label="Buscar na Inbox" class="h-9 w-56 rounded-md border border-line-strong bg-elevated px-3 text-sm text-fg outline-none focus:border-fg-muted" />
        <select id="inbox-project" v-model="projectFilter" name="inbox-project" data-test="inbox-project" aria-label="Projeto" class="h-9 rounded-md border border-line-strong bg-elevated px-2 text-sm text-fg">
          <option value="">Todos os projetos</option>
          <option v-for="p in projects.projects" :key="p.id" :value="String(p.id)">{{ p.name }}</option>
        </select>
        <button type="button" data-test="mark-all-read" class="h-9 rounded-md border border-line-strong px-3 text-sm text-fg hover:bg-card disabled:opacity-40" :disabled="marking" @click="markAll">Marcar todas como lidas</button>
      </div>
      <p v-if="error" data-test="inbox-error" role="alert" class="m-0 text-sm text-diff-del-fg">{{ error }}</p>
      <LoadStatus v-if="loadState !== 'ready'" :state="loadState" />
      <p v-else-if="groups.length === 0" data-test="empty" class="m-0 py-10 text-center text-fg-muted">{{ tab === 'pede-voce' ? 'Nada aguardando você agora.' : 'Nenhuma conversa aqui.' }}</p>
      <template v-else>
        <div
          ref="listEl"
          :role="triage ? 'listbox' : undefined"
          :tabindex="triage ? 0 : undefined"
          :aria-label="triage ? 'Conversas aguardando você' : undefined"
          :aria-activedescendant="triage && focusedId ? `inbox-option-${focusedId}` : undefined"
          class="group/list flex flex-col gap-4 rounded-md outline-none"
        >
          <section v-for="group in groups" :key="group.label" :role="triage ? 'group' : undefined" :aria-label="group.label" class="flex flex-col">
            <div class="flex items-center gap-3 py-2">
              <span class="h-px grow bg-line" /><span data-test="date-group" class="font-mono text-[0.6875rem] tracking-[0.08em] text-fg-subtle uppercase">{{ group.label }}</span><span class="h-px grow bg-line" />
            </div>
            <template v-if="triage">
              <InboxTriageRow
                v-for="s in group.sessions"
                :key="s.session_id"
                :ref="(el) => setRow(s.session_id, el)"
                :session="s"
                :focused="s.session_id === focusedId"
                @error="error = $event"
              />
            </template>
            <template v-else>
              <ConversationRow v-for="s in group.sessions" :key="s.session_id" :session="s" variant="inbox" @error="error = $event" />
            </template>
          </section>
        </div>
        <p v-if="triage" data-test="inbox-keys" class="m-0 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg-subtle">
          <span><kbd :class="kbdClass">j</kbd> <kbd :class="kbdClass">k</kbd> mover</span>
          <span><kbd :class="kbdClass">Enter</kbd> abrir</span>
          <span><kbd :class="kbdClass">a</kbd> permitir uma vez</span>
          <span><kbd :class="kbdClass">d</kbd> negar</span>
        </p>
      </template>
    </template>
    <p data-test="inbox-announce" role="status" class="sr-only">{{ announcement }}</p>
  </div>
</template>
