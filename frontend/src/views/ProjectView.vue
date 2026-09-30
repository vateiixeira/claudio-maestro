<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import SessionStateIcon from '../components/SessionStateIcon.vue'
import ConversationRow from '../components/conversation/ConversationRow.vue'
import ProjectGroups from '../components/groups/ProjectGroups.vue'
import SplitDivider from '../components/SplitDivider.vue'
import ConversationView from './ConversationView.vue'
import ProjectGitOverview from '../components/git/ProjectGitOverview.vue'
import { useGitStore } from '../stores/git'
import { errorMessage, openInEditor } from '../api/http'
import { groupByDate } from '../conversationList'
import { useGroupsStore } from '../stores/groups'
import { useProjectsStore } from '../stores/projects'
import { useNewConversationStore } from '../stores/newConversation'
import { useSessionsStore } from '../stores/sessions'
import { readSplitPercent, writeSplitPercent } from '../projectSplitPref'
import { useMediaQuery } from '../useMediaQuery'

// `session` is the conversation open beside the project (`?sessao=`).
const props = defineProps<{ id: number; session?: string }>()

const projects = useProjectsStore()
const sessions = useSessionsStore()
const git = useGitStore()
const repos = computed(() => git.reposFor(props.id))

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
  return wideScreen.value ? { name: 'project', params: { id: props.id }, query: { sessao: sessionId } } : undefined
}

const project = computed(() => projects.byId(props.id))
// The store keeps the order of the last listing, not of later `session.updated` events.
const projectSessions = computed(() =>
  [...sessions.forProject(props.id)].sort(
    (a, b) => b.last_activity_at - a.last_activity_at || b.created_at - a.created_at,
  ),
)

const groups = useGroupsStore()
const hasGroups = computed(() => groups.forProject(props.id).length > 0)
// A group this project does not know (not loaded, removed, or from another project) counts as none.
const knownGroupIds = computed(() => new Set(groups.forProject(props.id).map((g) => g.id)))
const ungrouped = computed(() =>
  projectSessions.value.filter((s) => s.group_id == null || !knownGroupIds.value.has(s.group_id)),
)
const dateGroups = computed(() => groupByDate(ungrouped.value, new Date(), true))

const sessionsError = ref<string | null>(null)
const actionError = ref<string | null>(null)

const renaming = ref(false)
const renameValue = ref('')
const renameError = ref<string | null>(null)
const renameInput = ref<HTMLInputElement | null>(null)

const confirmingRemove = ref(false)
const removeButton = ref<HTMLButtonElement | null>(null)
const cancelRemoveButton = ref<HTMLButtonElement | null>(null)
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
  removeButton.value?.focus()
}
const removing = ref(false)

async function load(): Promise<void> {
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
  if (!project.value) return
  editorError.value = null
  // Branches are secondary: a failure leaves the section out.
  git.load(props.id).catch(() => {})
  try {
    await sessions.loadForProject(props.id)
  } catch (e) {
    sessionsError.value = errorMessage(e)
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
  <div v-if="!project" class="px-10 py-8">
    <p v-if="projects.loaded" class="text-fg-muted">
      Projeto não encontrado.
      <RouterLink to="/inbox" class="text-primary-soft hover:underline">Voltar ao início</RouterLink>
    </p>
    <p v-else class="text-fg-muted">Carregando…</p>
  </div>

  <div v-else :class="split ? 'flex h-full min-w-0' : 'contents'">
    <div
      data-test="project-pane"
      class="flex flex-col gap-6"
      :class="split ? 'min-w-0 shrink-0 overflow-y-auto px-6 py-6 [&>*]:shrink-0' : 'max-w-5xl px-10 py-8'"
      :style="split ? { width: `${splitPercent}%` } : undefined"
    >
      <header class="flex flex-wrap items-start gap-4">
        <div class="flex min-w-0 flex-1 flex-col gap-1.5">
          <form
            v-if="renaming"
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
              class="h-11 min-w-0 flex-1 rounded-lg border border-line-strong bg-bg px-3.5 text-lg font-semibold text-fg outline-none focus:border-primary"
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
            <p v-if="renameError" role="alert" class="w-full text-sm text-secondary-soft">{{ renameError }}</p>
          </form>
          <div v-else class="flex min-w-0 items-center gap-3">
            <span class="size-3.5 shrink-0 rounded-[4px]" :style="{ backgroundColor: project.color }" />
            <h1 class="m-0 truncate text-[28px] font-semibold tracking-tight">{{ project.name }}</h1>
          </div>
          <div class="font-mono text-[13px] break-all text-fg-muted">{{ project.path }}</div>
        </div>

        <div class="flex flex-wrap items-center gap-2">
          <button
            type="button"
            data-test="open-editor"
            class="h-11 rounded-lg border border-line-strong px-4 font-medium text-fg hover:bg-card"
            @click="openEditor"
          >
            Abrir no editor
          </button>
          <button
            type="button"
            data-test="rename"
            class="h-11 rounded-lg border border-line-strong px-4 font-medium text-fg hover:bg-card"
            @click="startRename"
          >
            Renomear
          </button>
          <button
            type="button"
            ref="removeButton"
            data-test="remove"
            class="h-11 rounded-lg border border-line-strong px-4 font-medium text-fg hover:bg-card"
            @click="askRemove"
          >
            Remover
          </button>
          <button
            type="button"
            data-test="sync"
            title="Reler o histórico do CLI deste projeto"
            class="h-11 rounded-lg border border-line-strong px-4 font-medium text-fg hover:bg-card disabled:opacity-40"
            :disabled="syncing"
            @click="sync"
          >
            {{ syncing ? 'Atualizando…' : 'Atualizar' }}
          </button>
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
            Nova sessão
          </button>
        </div>
      </header>

      <p
        v-if="!project.available"
        id="new-session-hint"
        class="flex items-start gap-2 rounded-lg border border-secondary/40 bg-card px-4 py-3 text-sm text-secondary-soft"
      >
        <SessionStateIcon state="awaiting_decision" :size="14" class="mt-0.5" />
        <span>
          A pasta deste projeto não existe mais, então não é possível abrir sessões.
          Recrie a pasta no mesmo caminho ou remova o projeto.
        </span>
      </p>

      <p v-if="actionError" role="alert" class="rounded-lg border border-secondary/40 bg-card px-4 py-3 text-sm text-secondary-soft">
        {{ actionError }}
      </p>

      <p v-if="editorError" role="alert" class="rounded-lg border border-secondary/40 bg-card px-4 py-3 text-sm text-secondary-soft">
        {{ editorError }}
      </p>

      <section v-if="git.isLoaded(id)" data-test="repos" aria-labelledby="repos-title" class="flex flex-col gap-2">
        <h2 id="repos-title" class="m-0 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Repositórios nesta pasta</h2>
        <p v-if="repos.length === 0" class="m-0 text-sm text-fg-muted">sem repositório git</p>
        <ProjectGitOverview v-else :project-id="id" />
        <p v-if="git.limitReached(id)" data-test="repo-limit" class="m-0 text-xs text-secondary-soft">
          Mais de 50 repositórios; só os 50 primeiros são acompanhados.
        </p>
      </section>

      <section
        v-if="confirmingRemove"
        data-test="confirm-remove"
        role="alertdialog"
        aria-labelledby="confirm-remove-title"
        aria-describedby="confirm-remove-text"
        @keydown.esc.prevent="cancelRemove"
        class="flex flex-col gap-3 rounded-lg border border-secondary/60 bg-card px-5 py-4"
      >
        <h2 id="confirm-remove-title" class="m-0 text-base font-semibold">Remover o projeto {{ project.name }}?</h2>
        <p id="confirm-remove-text" class="m-0 text-sm text-fg-muted">
          A pasta e as conversas não são apagadas. O projeto só deixa de aparecer no Vibing.
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
            class="h-11 rounded-lg border border-line-strong px-4 font-medium text-fg hover:bg-panel"
            @click="cancelRemove"
          >
            Cancelar
          </button>
        </div>
      </section>

      <ProjectGroups
        :project-id="id"
        :available="project.available"
        :row-target="rowTarget"
        :active-id="split ? session ?? null : null"
        @error="actionError = $event"
      />

      <p v-if="sessionsError" role="alert" class="text-sm text-secondary-soft">{{ sessionsError }}</p>
      <p v-else-if="projectSessions.length === 0" class="text-sm text-fg-muted">
        Nenhuma conversa ainda. Use "Nova sessão" para começar uma conversa nesta pasta.
      </p>
      <template v-else>
        <h2 v-if="hasGroups && ungrouped.length" id="ungrouped-title" data-test="ungrouped-title" class="m-0 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Sem agrupador</h2>
        <section v-for="group in dateGroups" :key="group.label" :aria-label="group.label" class="flex flex-col">
          <div class="flex items-center gap-3 py-2">
            <span class="h-px grow bg-line" /><span data-test="date-group" class="font-mono text-[11px] tracking-[0.08em] text-fg-muted uppercase">{{ group.label }}</span><span class="h-px grow bg-line" />
          </div>
          <ConversationRow
            v-for="s in group.sessions"
            :key="s.session_id"
            :session="s"
            :to="rowTarget(s.session_id)"
            :active="split && s.session_id === session"
            @error="actionError = $event"
          />
        </section>
      </template>
    </div>
    <template v-if="split && session">
      <SplitDivider v-model="splitPercent" label="Largura da conversa" @change="writeSplitPercent" />
      <section data-test="conversation-pane" aria-label="Conversa" class="min-w-0 flex-1 overflow-hidden">
        <ConversationView :key="session" :id="session" :project-id="id" embedded />
      </section>
    </template>
  </div>
</template>
