<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ConversationRow from '../components/conversation/ConversationRow.vue'
import FirstSteps from '../components/FirstSteps.vue'
import LoadStatus from '../components/LoadStatus.vue'
import { errorMessage, markSessionsSeen } from '../api/http'
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
        <section v-for="group in groups" :key="group.label" :aria-label="group.label" class="flex flex-col">
          <div class="flex items-center gap-3 py-2">
            <span class="h-px grow bg-line" /><span data-test="date-group" class="font-mono text-[0.6875rem] tracking-[0.08em] text-fg-subtle uppercase">{{ group.label }}</span><span class="h-px grow bg-line" />
          </div>
          <ConversationRow v-for="s in group.sessions" :key="s.session_id" :session="s" variant="inbox" @error="error = $event" />
        </section>
      </template>
    </template>
  </div>
</template>
