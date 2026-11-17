<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import SessionStateIcon from '../components/SessionStateIcon.vue'
import ProjectConversations from '../components/project/ProjectConversations.vue'
import OrganizationView from './OrganizationView.vue'
import SplitDivider from '../components/SplitDivider.vue'
import ConversationView from './ConversationView.vue'
import GitPanel from '../components/git/GitPanel.vue'
import MoreMenu, { type MoreMenuItem } from '../components/ui/MoreMenu.vue'
import { useGitDetailsStore } from '../stores/gitDetails'
import { errorMessage, openInEditor } from '../api/http'
import { changedCount, useGitStore } from '../stores/git'
import { isScratch, useProjectsStore } from '../stores/projects'
import { useNewConversationStore } from '../stores/newConversation'
import { useSessionsStore } from '../stores/sessions'
import { isDiscarded } from '../conversation/marks'
import { shortPath } from '../projectsList'
import { readSplitPercent, writeSplitPercent } from '../projectSplitPref'
import { AGENTS_NAVIGATION_KEY } from '../agentsNavigation'
import { useMediaQuery } from '../useMediaQuery'

// `session` is the conversation open beside the project (`?sessao=`).
const props = defineProps<{ id: number; session?: string }>()

const navigation = inject(AGENTS_NAVIGATION_KEY, undefined)
const projects = useProjectsStore()
const sessions = useSessionsStore()
const gitDetails = useGitDetailsStore()
const repos = computed(() => gitDetails.reposFor(props.id))

const editorError = ref<string | null>(null)
async function openEditor(): Promise<void> {
  if (!project.value) return
  editorError.value = null
  try {
    await openInEditor(project.value.path)
  } catch (e) {
    editorError.value = errorMessage(e)
  }
}
const router = useRouter()
const route = useRoute()
const git = useGitStore()

// Wide screens split the view in two; narrow ones open a conversation on its own page.
const wideScreen = useMediaQuery('(min-width: 1200px)')
const split = computed(() => wideScreen.value && props.session != null)
const splitPercent = ref(readSplitPercent())
watch(
  [() => props.session, wideScreen],
  ([session, wide]) => {
    if (session != null && !wide) void router.replace({ name: 'session', params: { id: session } })
  },
  { immediate: true },
)
function rowTarget(sessionId: string) {
  return wideScreen.value ? { name: 'project', params: { id: props.id }, query: { ...route.query, sessao: sessionId } } : undefined
}

const project = computed(() => projects.byId(props.id))
// The built-in "Sem projeto" shows only its conversations: no path, git or project actions.
const scratch = computed(() => isScratch(project.value))
const TABS = [
  { id: 'conversas', label: 'Conversas' },
  { id: 'git', label: 'Git' },
  { id: 'organizacao', label: 'Organização' },
] as const
type ProjectTab = (typeof TABS)[number]['id']
const activeTab = computed<ProjectTab>(() => scratch.value ? 'conversas' : TABS.find(tab => tab.id === route.query.visao)?.id ?? 'git')
const tabButtons = ref<HTMLButtonElement[]>([])
async function selectTab(tab: ProjectTab): Promise<void> {
  if (activeTab.value === tab) return
  await router.push({ query: { ...route.query, visao: tab } })
}
async function tabKey(event: KeyboardEvent, index: number): Promise<void> {
  const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
  if (!step && event.key !== 'Home' && event.key !== 'End') return
  event.preventDefault()
  const target = event.key === 'Home' ? 0 : event.key === 'End' ? TABS.length - 1 : (index + step + TABS.length) % TABS.length
  await selectTab(TABS[target]!.id)
  await nextTick()
  tabButtons.value[target]?.focus()
}
const summaryRepos = computed(() => git.reposFor(props.id))
// "N em aberto": this project's conversations that are neither finished nor discarded.
const openConversations = computed(() => sessions.all.filter(session => session.project_id === props.id && session.display_state !== 'finished' && !isDiscarded(session)).length)
// "N com pendências": repositories with changed files or commits to push. No count until git has loaded.
const pendingRepos = computed(() => git.isLoaded(props.id) ? summaryRepos.value.filter(repo => changedCount(repo) > 0 || (repo.ahead ?? 0) > 0).length : 0)
const tabCount = computed<Record<ProjectTab, string | null>>(() => ({
  conversas: `${openConversations.value} em aberto`,
  git: pendingRepos.value ? `${pendingRepos.value} com ${pendingRepos.value === 1 ? 'pendência' : 'pendências'}` : null,
  organizacao: null,
}))
watch([() => props.id, project], () => {
  if (project.value && !scratch.value && project.value.available && activeTab.value !== 'git') git.ensure(props.id)
}, { immediate: true })

const sessionsLoading = ref(false)
const sessionsError = ref<string | null>(null)
const actionError = ref<string | null>(null)

const renaming = ref(false)
const renameValue = ref('')
const renameError = ref<string | null>(null)
const renameInput = ref<HTMLInputElement | null>(null)

const confirmingRemove = ref(false)
const cancelRemoveButton = ref<HTMLButtonElement | null>(null)
const actionsRoot = ref<InstanceType<typeof MoreMenu> | null>(null)
// Opening the confirmation puts focus on the safe choice; closing it gives focus back.
async function askRemove() {
  confirmingRemove.value = true
  renaming.value = false
  await nextTick()
  cancelRemoveButton.value?.focus()
}
async function cancelRemove() {
  confirmingRemove.value = false
  await nextTick()
  const root = actionsRoot.value?.$el as HTMLElement | undefined
  root?.querySelector<HTMLButtonElement>('[data-test="project-actions"]')?.focus()
}
const removing = ref(false)

let loadTicket = 0
onBeforeUnmount(() => { loadTicket++ })
async function load(): Promise<void> {
  const ticket = ++loadTicket
  const projectId = props.id
  const current = () => ticket === loadTicket && props.id === projectId
  sessionsError.value = null
  actionError.value = null
  renaming.value = false
  confirmingRemove.value = false
  if (!projects.loaded) {
    try {
      await projects.load()
    } catch {
      return
    }
  }
  if (!current() || !project.value) return
  editorError.value = null
  sessionsLoading.value = true
  try {
    await sessions.loadForProject(projectId)
  } catch (e) {
    if (current()) sessionsError.value = errorMessage(e)
  } finally {
    if (current()) sessionsLoading.value = false
  }
}

watch(() => props.id, load, { immediate: true })

const syncing = ref(false)
async function sync(): Promise<void> {
  if (syncing.value) return
  syncing.value = true
  actionError.value = null
  try {
    await sessions.sync(props.id)
    // Hidden counts live in the project list.
    await projects.load()
  } catch (e) {
    actionError.value = errorMessage(e)
  } finally {
    syncing.value = false
  }
}

const actionItems = computed<MoreMenuItem[]>(() => [
  { id: 'rename', label: 'Renomear' },
  { id: 'remove', label: 'Remover', danger: true },
  { id: 'sync', label: syncing.value ? 'Atualizando…' : 'Atualizar', title: 'Reler o histórico do CLI deste projeto', disabled: syncing.value },
])
function runAction(id: string): void {
  if (id === 'rename') void startRename()
  else if (id === 'remove') void askRemove()
  else if (id === 'sync') void sync()
}

function newSession(): void {
  if (!project.value?.available) return
  useNewConversationStore().open(props.id)
}

async function startRename(): Promise<void> {
  renameValue.value = project.value?.name ?? ''
  renameError.value = null
  confirmingRemove.value = false
  renaming.value = true
  await nextTick()
  renameInput.value?.focus()
  renameInput.value?.select()
}

async function saveRename(): Promise<void> {
  const name = renameValue.value.trim()
  if (!name) {
    renameError.value = 'O nome não pode ficar vazio.'
    return
  }
  try {
    await projects.rename(props.id, name)
    renaming.value = false
  } catch (e) {
    renameError.value = errorMessage(e)
  }
}

async function remove(): Promise<void> {
  removing.value = true
  actionError.value = null
  try {
    await projects.remove(props.id)
    await router.push('/inbox')
  } catch (e) {
    actionError.value = errorMessage(e)
    confirmingRemove.value = false
  } finally {
    removing.value = false
  }
}
</script>

<template>
  <div v-if="!project" class="px-4 py-8 sm:px-10">
    <button v-if="navigation?.enabled.value" type="button" data-test="project-mobile-menu" class="flex size-9 shrink-0 items-center justify-center rounded-md text-fg-muted hover:bg-card hover:text-fg" aria-label="Abrir navegação" :aria-expanded="navigation.open.value" @click="navigation.toggle($event.currentTarget as HTMLElement)"><svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" /></svg></button>
    <p v-if="projects.loaded" class="text-fg-muted">
      Projeto não encontrado.
      <RouterLink to="/inbox" class="text-info-soft hover:underline">Voltar ao início</RouterLink>
    </p>
    <p v-else class="text-fg-muted">Carregando…</p>
  </div>

  <div v-else :class="split ? 'flex h-full min-w-0' : 'contents'">
    <div
      data-test="project-pane"
      class="flex flex-col gap-6"
      :class="split ? 'min-w-0 shrink-0 overflow-y-auto px-6 py-6 [&>*]:shrink-0' : 'min-w-0 w-full px-4 py-6 sm:px-8'"
      :style="split ? { width: `${splitPercent}%` } : undefined"
    >
      <nav v-if="!scratch" aria-label="Caminho do projeto" class="flex items-center gap-2 text-sm text-fg-muted">
        <RouterLink to="/projects" class="rounded hover:text-fg focus-visible:outline-2 focus-visible:outline-primary">Projetos</RouterLink>
        <span aria-hidden="true">/</span><span class="truncate font-medium text-fg">{{ project.name }}</span>
      </nav>
      <header class="flex flex-wrap items-center gap-3">
        <button v-if="navigation?.enabled.value" type="button" data-test="project-mobile-menu" class="flex size-9 shrink-0 items-center justify-center rounded-md text-fg-muted hover:bg-card hover:text-fg" aria-label="Abrir navegação" :aria-expanded="navigation.open.value" @click="navigation.toggle($event.currentTarget as HTMLElement)"><svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" /></svg></button>
        <form
          v-if="renaming && !scratch"
          data-test="rename-form"
          class="flex min-w-0 flex-1 flex-wrap items-center gap-2"
          @submit.prevent="saveRename"
          @keydown.esc.prevent="renaming = false"
        >
          <label for="rename-project" class="sr-only">Nome do projeto</label>
          <input
            id="rename-project"
            ref="renameInput"
            v-model="renameValue"
            type="text"
            maxlength="100"
            class="h-11 min-w-0 flex-1 rounded-lg border border-line-strong bg-elevated px-3.5 text-lg font-semibold text-fg outline-none focus:border-fg-muted"
          />
          <button type="submit" class="h-11 rounded-lg bg-primary px-4 font-semibold text-primary-fg hover:bg-primary-soft">
            Salvar
          </button>
          <button
            type="button"
            class="h-11 rounded-lg border border-line-strong px-4 font-medium text-fg hover:bg-card"
            @click="renaming = false"
          >
            Cancelar
          </button>
          <p v-if="renameError" role="alert" class="w-full text-sm text-diff-del-fg">{{ renameError }}</p>
        </form>
        <div v-else class="flex min-w-0 flex-1 items-center gap-3">
          <span class="size-[11px] shrink-0 rounded-[3px]" :style="{ backgroundColor: project.color }" />
          <h1 class="m-0 min-w-0 truncate text-2xl font-semibold tracking-tight">{{ project.name }}</h1>
          <span v-if="!scratch" data-test="project-path" :title="project.path" class="min-w-0 shrink-[2] truncate font-mono text-[0.78125rem] text-fg-subtle">{{ shortPath(project.path) }}</span>
        </div>

        <div class="flex flex-wrap items-center gap-2">
          <button
            v-if="!scratch"
            type="button"
            data-test="open-editor"
            class="inline-flex h-9 items-center rounded-[10px] border border-line-strong px-3.5 text-[0.84375rem] font-medium whitespace-nowrap text-fg hover:bg-card focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
            @click="openEditor"
          >
            Abrir no editor
          </button>
          <MoreMenu
            v-if="!scratch"
            ref="actionsRoot"
            data-test="project-actions"
            label="Mais ações do projeto"
            :items="actionItems"
            class="[&>button]:size-9 [&>button]:rounded-[10px] [&>button]:border [&>button]:border-line-strong [&>button]:text-fg-muted"
            @select="runAction"
          />
          <button
            type="button"
            data-test="new-session"
            class="inline-flex h-9 items-center gap-2 rounded-[10px] bg-primary px-3.5 text-[0.84375rem] font-semibold whitespace-nowrap text-primary-fg hover:bg-primary-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-primary"
            :disabled="!project.available"
            :aria-describedby="project.available ? undefined : 'new-session-hint'"
            @click="newSession"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            Nova conversa
          </button>
        </div>
      </header>

      <p
        v-if="!project.available && !scratch"
        id="new-session-hint"
        class="flex items-start gap-2 rounded-lg border border-secondary/40 bg-card px-4 py-3 text-sm text-secondary-soft"
      >
        <SessionStateIcon state="awaiting_decision" :size="14" class="mt-0.5" />
        <span>
          A pasta deste projeto não existe mais, então não é possível abrir sessões.
          Recrie a pasta no mesmo caminho ou remova o projeto.
        </span>
      </p>

      <p v-if="actionError" role="alert" class="rounded-lg border border-diff-del-fg/40 bg-diff-del-bg px-4 py-3 text-sm text-diff-del-fg">
        {{ actionError }}
      </p>

      <p v-if="editorError" role="alert" class="rounded-lg border border-diff-del-fg/40 bg-diff-del-bg px-4 py-3 text-sm text-diff-del-fg">
        {{ editorError }}
      </p>

      <section
        v-if="confirmingRemove && !scratch"
        data-test="confirm-remove"
        role="alertdialog"
        aria-labelledby="confirm-remove-title"
        aria-describedby="confirm-remove-text"
        @keydown.esc.prevent="cancelRemove"
        class="flex flex-col gap-3 rounded-lg border border-secondary/60 bg-card px-5 py-4"
      >
        <h2 id="confirm-remove-title" class="m-0 text-base font-semibold">Remover o projeto {{ project.name }}?</h2>
        <p id="confirm-remove-text" class="m-0 text-sm text-fg-muted">
          A pasta e as conversas não são apagadas. O projeto só deixa de aparecer no Maestro.
          <span class="font-mono text-xs break-all text-fg">{{ project.path }}</span>
          continua como está.
        </p>
        <div class="flex gap-2">
          <button
            type="button"
            data-test="confirm-remove-ok"
            class="h-11 rounded-lg bg-secondary px-4 font-semibold text-secondary-fg hover:bg-secondary-soft disabled:opacity-40"
            :disabled="removing"
            @click="remove"
          >
            {{ removing ? 'Removendo…' : 'Remover projeto' }}
          </button>
          <button
            type="button"
            ref="cancelRemoveButton"
            data-test="confirm-remove-cancel"
            class="h-11 rounded-lg border border-line-strong px-4 font-medium text-fg hover:bg-elevated"
            @click="cancelRemove"
          >
            Cancelar
          </button>
        </div>
      </section>

      <div v-if="!scratch" role="tablist" aria-label="Áreas do projeto" class="flex min-w-0 gap-1 overflow-x-auto border-b border-line">
        <button v-for="(tab, index) in TABS" :key="tab.id" :ref="el => { if (el) tabButtons[index] = el as HTMLButtonElement }" :id="`project-tab-${tab.id}`" type="button" role="tab" :data-test="`project-tab-${tab.id}`" :aria-selected="activeTab === tab.id" aria-controls="project-tabpanel" :tabindex="activeTab === tab.id ? 0 : -1" class="-mb-px flex h-11 shrink-0 items-center gap-2 border-0 border-b-2 bg-transparent px-3 text-[0.90625rem] font-medium whitespace-nowrap focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-primary" :class="activeTab === tab.id ? 'border-primary text-fg' : 'border-transparent text-fg-muted hover:text-fg'" @click="selectTab(tab.id)" @keydown="tabKey($event, index)">
          {{ tab.label }}<span v-if="tabCount[tab.id]" data-test="project-tab-count" class="font-mono text-[0.71875rem] tabular-nums" :class="tab.id === 'git' ? 'text-secondary-soft' : 'text-fg-subtle'">{{ tabCount[tab.id] }}</span>
        </button>
      </div>
      <div id="project-tabpanel" :role="scratch ? undefined : 'tabpanel'" :aria-labelledby="scratch ? undefined : `project-tab-${activeTab}`" class="min-w-0">
        <ProjectConversations v-show="activeTab === 'conversas'" :project-id="id" :available="project.available" :row-target="rowTarget" :active-id="split ? session ?? null : null" :loading="sessionsLoading" :load-error="sessionsError" @retry="load" @error="actionError = $event" />
      <section v-if="activeTab === 'git'" data-test="repos" class="flex flex-col gap-3">
        <p v-if="gitDetails.isLoaded(id) && repos.length === 0 && !gitDetails.errorFor(id)" class="m-0 text-sm text-fg-muted">sem repositório git</p>
        <GitPanel :project-id="id" />
        <p v-if="gitDetails.byProject[id]?.limit_reached" data-test="repo-limit" class="m-0 text-xs text-fg-muted">
          Mais de 50 repositórios; só os 50 primeiros são acompanhados.
        </p>
      </section>

        <OrganizationView v-if="activeTab === 'organizacao'" :project-id="id" embedded :compact="split" />
      </div>
    </div>
    <template v-if="split && session">
      <SplitDivider v-model="splitPercent" label="Largura da conversa" @change="writeSplitPercent" />
      <section data-test="conversation-pane" aria-label="Conversa" class="min-w-0 flex-1 overflow-hidden">
        <ConversationView :key="session" :id="session" :project-id="id" embedded />
      </section>
    </template>
  </div>
</template>
