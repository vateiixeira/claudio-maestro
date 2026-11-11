<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import SessionStateIcon from '../components/SessionStateIcon.vue'
import ProjectConversations from '../components/project/ProjectConversations.vue'
import OrganizationView from './OrganizationView.vue'
import SplitDivider from '../components/SplitDivider.vue'
import ConversationView from './ConversationView.vue'
import ScmSection from '../components/git/scm/ScmSection.vue'
import CommitsSection from '../components/git/commits/CommitsSection.vue'
import { useGitDetailsStore } from '../stores/gitDetails'
import { errorMessage, openInEditor } from '../api/http'
import { changedCount, useGitStore } from '../stores/git'
import { isScratch, useProjectsStore } from '../stores/projects'
import { useNewConversationStore } from '../stores/newConversation'
import { useSessionsStore } from '../stores/sessions'
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
const activeTab = computed<ProjectTab>(() => scratch.value ? 'conversas' : TABS.find(tab => tab.id === route.query.visao)?.id ?? 'conversas')
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
const gitSummary = computed(() => {
  if (!git.isLoaded(props.id)) return 'Git: ver repositórios'
  if (!summaryRepos.value.length) return 'Git: sem repositório'
  const changes = summaryRepos.value.reduce((sum, repo) => sum + changedCount(repo), 0)
  const ahead = summaryRepos.value.reduce((sum, repo) => sum + (repo.ahead ?? 0), 0)
  const errors = summaryRepos.value.some(repo => repo.error)
  return `Git: ${changes} ${changes === 1 ? 'alteração' : 'alterações'} · ${ahead} para enviar${errors ? ' · leitura parcial' : ''}`
})
watch([() => props.id, project], () => {
  if (project.value && !scratch.value && project.value.available && activeTab.value !== 'git') git.ensure(props.id)
}, { immediate: true })

const actionsOpen = ref(false)
const actionsRoot = ref<HTMLElement | null>(null)
const actionsButton = ref<HTMLButtonElement | null>(null)
async function closeActions(): Promise<void> {
  actionsOpen.value = false
  await nextTick()
  actionsButton.value?.focus()
}
async function actionsKey(event: KeyboardEvent): Promise<void> {
  if (event.key === 'Escape') { event.preventDefault(); await closeActions(); return }
  const keys = ['ArrowDown', 'ArrowUp', 'Home', 'End']
  if (!keys.includes(event.key)) return
  event.preventDefault()
  if (!actionsOpen.value) { actionsOpen.value = true; await nextTick() }
  const items = [...(actionsRoot.value?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)') ?? [])]
  const current = items.indexOf(document.activeElement as HTMLButtonElement)
  const target = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : current < 0 ? (event.key === 'ArrowUp' ? items.length - 1 : 0) : (current + (event.key === 'ArrowUp' ? -1 : 1) + items.length) % items.length
  items[target]?.focus()
}
function actionsBlur(event: FocusEvent): void {
  if (event.relatedTarget instanceof Node && !actionsRoot.value?.contains(event.relatedTarget)) actionsOpen.value = false
}
function outsideActions(event: PointerEvent): void {
  if (event.target instanceof Node && !actionsRoot.value?.contains(event.target)) actionsOpen.value = false
}
onMounted(() => document.addEventListener('pointerdown', outsideActions))
onBeforeUnmount(() => document.removeEventListener('pointerdown', outsideActions))
const sessionsLoading = ref(false)
const sessionsError = ref<string | null>(null)
const actionError = ref<string | null>(null)

const renaming = ref(false)
const renameValue = ref('')
const renameError = ref<string | null>(null)
const renameInput = ref<HTMLInputElement | null>(null)

const confirmingRemove = ref(false)
const cancelRemoveButton = ref<HTMLButtonElement | null>(null)
// Opening the confirmation puts focus on the safe choice; closing it gives focus back.
async function askRemove() {
  actionsOpen.value = false
  confirmingRemove.value = true
  renaming.value = false
  await nextTick()
  cancelRemoveButton.value?.focus()
}
async function cancelRemove() {
  confirmingRemove.value = false
  await nextTick()
  actionsButton.value?.focus()
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
  actionsOpen.value = false
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

function newSession(): void {
  if (!project.value?.available) return
  useNewConversationStore().open(props.id)
}

async function startRename(): Promise<void> {
  actionsOpen.value = false
  renameValue.value = project.value?.name ?? ''
  renameError.value = null
  confirmingRemove.value = false
  renaming.value = true
  await nextTick()
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
      <header class="flex flex-wrap items-start gap-4">
        <button v-if="navigation?.enabled.value" type="button" data-test="project-mobile-menu" class="flex size-9 shrink-0 items-center justify-center rounded-md text-fg-muted hover:bg-card hover:text-fg" aria-label="Abrir navegação" :aria-expanded="navigation.open.value" @click="navigation.toggle($event.currentTarget as HTMLElement)"><svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" /></svg></button>
        <div class="flex min-w-0 flex-1 flex-col gap-1.5">
          <form
            v-if="renaming && !scratch"
            data-test="rename-form"
            class="flex flex-wrap items-center gap-2"
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
          <div v-else class="flex min-w-0 items-center gap-3">
            <span class="size-3.5 shrink-0 rounded-[4px]" :style="{ backgroundColor: project.color }" />
            <h1 class="m-0 truncate text-[1.75rem] font-semibold tracking-tight">{{ project.name }}</h1>
          </div>
          <div v-if="!scratch" class="text-sm break-all text-fg-subtle">{{ project.path }}</div>
          <button v-if="!scratch && project.available" type="button" data-test="project-git-summary" class="self-start rounded border-0 bg-transparent p-0 text-left text-sm text-fg-muted underline decoration-line-strong underline-offset-4 hover:text-fg focus-visible:outline-2 focus-visible:outline-primary" @click="selectTab('git')">{{ gitSummary }}</button>
        </div>

        <div class="flex flex-wrap items-center gap-2">
          <button
            v-if="!scratch"
            type="button"
            data-test="open-editor"
            class="h-11 rounded-lg border border-line-strong px-4 font-medium text-fg hover:bg-card"
            @click="openEditor"
          >
            Abrir no editor
          </button>
          <div v-if="!scratch" ref="actionsRoot" class="relative" @keydown="actionsKey" @focusout="actionsBlur">
            <button ref="actionsButton" type="button" data-test="project-actions" aria-label="Mais ações do projeto" aria-haspopup="menu" :aria-expanded="actionsOpen" class="flex h-11 w-11 items-center justify-center rounded-lg border border-line-strong text-xl text-fg hover:bg-card focus-visible:outline-2 focus-visible:outline-primary" @click="actionsOpen = !actionsOpen"><svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="19" cy="12" r="1.6" /></svg></button>
            <div v-if="actionsOpen" role="menu" aria-label="Ações do projeto" class="absolute right-0 top-12 z-30 flex min-w-44 flex-col rounded-lg border border-line-strong bg-surface p-1 shadow-lg">
              <button type="button" role="menuitem" data-test="rename" class="rounded px-3 py-2 text-left text-sm hover:bg-card focus-visible:outline-2 focus-visible:outline-primary" @click="startRename">Renomear</button>
              <button type="button" role="menuitem" data-test="remove" class="rounded px-3 py-2 text-left text-sm hover:bg-card focus-visible:outline-2 focus-visible:outline-primary" @click="askRemove">Remover</button>
              <button type="button" role="menuitem" data-test="sync" title="Reler o histórico do CLI deste projeto" :disabled="syncing" class="rounded px-3 py-2 text-left text-sm hover:bg-card disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-primary" @click="sync">{{ syncing ? 'Atualizando…' : 'Atualizar' }}</button>
            </div>
          </div>
          <button
            type="button"
            data-test="new-session"
            class="flex h-11 items-center gap-2 rounded-lg bg-primary px-4 font-semibold text-primary-fg hover:bg-primary-soft disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-primary"
            :disabled="!project.available"
            :aria-describedby="project.available ? undefined : 'new-session-hint'"
            @click="newSession"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true">
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

      <div v-if="!scratch" role="tablist" aria-label="Áreas do projeto" class="flex min-w-0 gap-2 border-b border-line sm:gap-5">
        <button v-for="(tab, index) in TABS" :key="tab.id" :ref="el => { if (el) tabButtons[index] = el as HTMLButtonElement }" :id="`project-tab-${tab.id}`" type="button" role="tab" :data-test="`project-tab-${tab.id}`" :aria-selected="activeTab === tab.id" aria-controls="project-tabpanel" :tabindex="activeTab === tab.id ? 0 : -1" class="-mb-px flex h-11 items-center gap-2 border-0 border-b-3 bg-transparent px-2 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-primary sm:px-4" :class="activeTab === tab.id ? 'border-primary text-fg' : 'border-transparent text-fg-muted hover:text-fg'" @click="selectTab(tab.id)" @keydown="tabKey($event, index)">
          {{ tab.label }}<span v-if="tab.id === 'git' && git.isLoaded(id)" class="rounded-full bg-card px-2 py-0.5 text-xs">{{ summaryRepos.length }}</span>
        </button>
      </div>
      <div id="project-tabpanel" :role="scratch ? undefined : 'tabpanel'" :aria-labelledby="scratch ? undefined : `project-tab-${activeTab}`" class="min-w-0">
        <ProjectConversations v-show="activeTab === 'conversas'" :project-id="id" :available="project.available" :row-target="rowTarget" :active-id="split ? session ?? null : null" :loading="sessionsLoading" :load-error="sessionsError" @retry="load" @error="actionError = $event" />
      <section v-if="activeTab === 'git'" data-test="repos" class="flex flex-col gap-3">
        <p v-if="gitDetails.isLoaded(id) && repos.length === 0 && !gitDetails.errorFor(id)" class="m-0 text-sm text-fg-muted">sem repositório git</p>
        <ScmSection v-show="!gitDetails.isLoaded(id) || repos.length > 0 || gitDetails.errorFor(id)" :project-id="id" />
        <CommitsSection v-if="project?.available" :project-id="id" />
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
