<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import BrandMark from '../BrandMark.vue'
import ConnectionIndicator from '../ConnectionIndicator.vue'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import SessionSearch from './SessionSearch.vue'
import SidebarGroups from './SidebarGroups.vue'
import SidebarLane from './SidebarLane.vue'
import SidebarSessionRow from './SidebarSessionRow.vue'
import { looseOpenSessions } from './openList'
import { sidebarItemClass } from './itemClass'
import { needsYou } from '../../conversation/needsYou'
import { useEventSocket } from '../../api/socket'
import { isCollapsed, isSectionOpened, setCollapsed, setSectionOpened } from '../../sidebarCollapse'
import { splitProjects } from '../../sidebarTree'
import { SIDEBAR_DEFAULT_WIDTH, SIDEBAR_KEY_STEP, SIDEBAR_MAX_WIDTH, SIDEBAR_MIN_WIDTH, clampSidebarWidth, sidebarWidth, writeSidebarWidth } from '../../sidebarWidthPref'
import { repoLabel, useGitStore } from '../../stores/git'
import { useGroupsStore } from '../../stores/groups'
import { useNewConversationStore } from '../../stores/newConversation'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import { useUpdatesStore } from '../../stores/updates'
import type { Project, Session } from '../../types/api'
import IconChat from '../icons/IconChat.vue'
import IconChevron from '../icons/IconChevron.vue'
import IconDashboard from '../icons/IconDashboard.vue'
import IconInbox from '../icons/IconInbox.vue'
import IconPlus from '../icons/IconPlus.vue'
import IconSettings from '../icons/IconSettings.vue'

const projects = useProjectsStore()
const sessions = useSessionsStore()
const git = useGitStore()
const groups = useGroupsStore()
const newConversation = useNewConversationStore()
const updates = useUpdatesStore()
const route = useRoute()
const socket = useEventSocket()

// The handle sits on the right edge: moving the pointer right makes the sidebar wider.
let drag: { startX: number; startWidth: number } | null = null
function startResize(event: PointerEvent) {
  event.preventDefault()
  ;(event.currentTarget as HTMLElement | null)?.setPointerCapture?.(event.pointerId)
  drag = { startX: event.clientX, startWidth: sidebarWidth.value }
}
function moveResize(event: PointerEvent) {
  if (!drag) return
  sidebarWidth.value = clampSidebarWidth(drag.startWidth + (event.clientX - drag.startX))
}
function endResize() {
  if (!drag) return
  drag = null
  writeSidebarWidth(sidebarWidth.value)
}
function onResizeKey(event: KeyboardEvent) {
  const delta = event.key === 'ArrowRight' ? SIDEBAR_KEY_STEP : event.key === 'ArrowLeft' ? -SIDEBAR_KEY_STEP : 0
  if (!delta) return
  event.preventDefault()
  sidebarWidth.value = clampSidebarWidth(sidebarWidth.value + delta)
  writeSidebarWidth(sidebarWidth.value)
}
function resetResize() {
  sidebarWidth.value = SIDEBAR_DEFAULT_WIDTH
  writeSidebarWidth(sidebarWidth.value)
}

// Only the waits that need you count; an ordinary wait with nothing new is not a reason to look.
const isWaitingOnYou = (s: Session) => s.display_state === 'waiting' && needsYou(s)
const waitingCount = computed(() => sessions.all.filter(isWaitingOnYou).length)
function waitingIn(projectId: number): number {
  return sessions.forProject(projectId).filter(isWaitingOnYou).length
}
function runningIn(projectId: number): boolean {
  return sessions.forProject(projectId).some((s) => s.display_state === 'running')
}
// Open conversations of each project outside its groups, the ones waiting for you first; grouped ones show under their group.
// Built once per change so the template reads it instead of recomputing per project.
const looseByProject = computed(() => {
  const map = new Map<number, Session[]>()
  for (const p of projects.projects) {
    map.set(p.id, looseOpenSessions(sessions.all, p.id, new Set(groups.forProject(p.id).map((g) => g.id))))
  }
  return map
})
function hasChildren(projectId: number): boolean {
  return groups.forProject(projectId).length > 0 || (looseByProject.value.get(projectId)?.length ?? 0) > 0
}
// "Em andamento": projects with an open conversation. "Outros projetos": the rest, kept in one folded line.
const split = computed(() => splitProjects(projects.projects, sessions.all))
// The project on screen stays visible even when it has no open conversation and the list is folded.
const activeIsOther = computed(() => split.value.others.some((p) => p.id === activeProjectId.value))
const othersOpen = computed(() => isSectionOpened('others') || activeIsOther.value)
function toggleOthers() {
  setSectionOpened('others', !isSectionOpened('others'))
}
// The branch label only renders for an available project inside a git repository.
function showsBranch(project: Project): boolean {
  return project.available && Boolean(git.reposFor(project.id)[0])
}
// The project being looked at, directly or through one of its conversations.
const activeProjectId = computed<number | null>(() => {
  if (route.name === 'project') return Number(route.params.id)
  if (route.name === 'session') return sessions.find(String(route.params.id))?.project_id ?? null
  return null
})
const currentProjectId = computed(() => activeProjectId.value)
// The group of the open conversation, so a new one starts next to it.
// `null` = the conversation has no group; `undefined` = no conversation open, so no preference.
const currentGroupId = computed<number | null | undefined>(() => {
  if (route.name !== 'session') return undefined
  const session = sessions.find(String(route.params.id))
  return session ? (session.group_id ?? null) : undefined
})
const itemClass = sidebarItemClass
</script>

<template>
  <nav aria-label="Navegação" :style="{ width: `${sidebarWidth}px` }" class="relative flex h-full shrink-0 flex-col border-r border-line-strong bg-bg text-[0.84375rem]">
    <div
      data-test="sidebar-resize"
      role="separator"
      aria-orientation="vertical"
      aria-label="Redimensionar menu lateral"
      tabindex="0"
      :aria-valuenow="sidebarWidth"
      :aria-valuemin="SIDEBAR_MIN_WIDTH"
      :aria-valuemax="SIDEBAR_MAX_WIDTH"
      title="Arraste para redimensionar · duplo clique volta ao padrão"
      class="absolute inset-y-0 -right-1 z-10 w-2 cursor-col-resize touch-none hover:bg-line-strong focus-visible:bg-fg-muted/40 focus-visible:outline-none"
      @pointerdown="startResize"
      @pointermove="moveResize"
      @pointerup="endResize"
      @pointercancel="endResize"
      @dblclick="resetResize"
      @keydown="onResizeKey"
    />
    <RouterLink to="/inbox" class="flex min-h-11 items-center gap-2 px-4 pt-3 pb-1.5 text-fg no-underline">
      <BrandMark />
      <span class="text-[0.9375rem] font-semibold tracking-tight">Cláudio Maestro</span>
    </RouterLink>

    <div class="flex flex-col gap-1.5 px-2.5 pb-2.5">
      <button
        type="button"
        data-test="nav-new"
        class="flex h-9 w-full items-center gap-2 rounded-lg border border-line-strong bg-surface px-2.5 text-left font-medium text-fg hover:bg-card focus-visible:outline-2 focus-visible:outline-primary"
        @click="newConversation.open(currentProjectId, currentGroupId)"
      >
        <span class="text-primary"><IconPlus :size="15" /></span>
        <span class="grow">Nova conversa</span>
        <kbd class="rounded border border-line-strong px-1.5 font-mono text-[0.6875rem] text-fg-subtle">C</kbd>
      </button>
      <SessionSearch />
    </div>

    <div class="flex flex-col gap-px px-2.5 pb-2">
      <RouterLink to="/inbox" data-test="nav-inbox" :class="itemClass(route.name === 'inbox')" :aria-current="route.name === 'inbox' ? 'page' : undefined">
        <IconInbox />
        <span class="grow">Inbox</span>
        <span v-if="waitingCount" class="flex shrink-0 items-center gap-1 text-xs font-semibold text-secondary">
          <DisplayStateIcon display="waiting" :size="11" /><span data-test="inbox-count">{{ waitingCount }}</span><span class="sr-only"> aguardando você</span>
        </span>
      </RouterLink>
      <RouterLink to="/dashboard" data-test="nav-dashboard" :class="itemClass(route.name === 'dashboard')" :aria-current="route.name === 'dashboard' ? 'page' : undefined">
        <IconDashboard /><span class="grow">Dashboard</span>
      </RouterLink>
      <RouterLink to="/sessions" data-test="nav-conversations" :class="itemClass(route.name === 'sessions')" :aria-current="route.name === 'sessions' ? 'page' : undefined">
        <IconChat /><span class="grow">Conversas</span>
      </RouterLink>
    </div>

    <div data-test="sidebar-sections" class="flex min-h-0 flex-1 flex-col gap-[22px] overflow-y-auto px-2.5 pt-3.5 pb-2">
      <section aria-labelledby="sidebar-active-title" class="flex flex-col gap-px">
        <div class="flex h-[30px] items-center pr-1 pl-2.5">
          <h2 id="sidebar-active-title" data-test="section-title" class="grow font-mono text-[0.6875rem] font-normal tracking-[0.08em] text-fg-subtle uppercase">Em andamento</h2>
          <RouterLink to="/projects/new" data-test="new-project" aria-label="Novo projeto" class="flex size-[26px] items-center justify-center rounded-md text-fg-subtle no-underline hover:bg-card hover:text-fg"><IconPlus :size="13" /></RouterLink>
        </div>
        <p v-if="projects.loadError" class="px-2.5 py-2 text-xs text-diff-del-fg" role="alert">Não foi possível carregar os projetos. {{ projects.loadError }}</p>
        <p v-else-if="projects.loaded && projects.projects.length === 0" class="px-2.5 py-2 text-xs text-fg-muted">Nenhum projeto ainda.</p>
        <p v-else-if="projects.projects.length > 0 && split.active.length === 0" data-test="no-open" class="px-2.5 py-1 text-xs text-fg-subtle">Nenhuma conversa aberta</p>
        <template v-for="(project, index) in split.active" :key="project.id">
          <div class="flex items-center" :class="{ 'mt-1.5': index > 0 }">
            <RouterLink
              data-test="project"
              :data-available="String(project.available)"
              :to="{ name: 'project', params: { id: project.id } }"
              :class="[itemClass(activeProjectId === project.id), 'min-w-0 grow py-1']"
              :aria-current="route.name === 'project' && activeProjectId === project.id ? 'page' : undefined"
            >
              <span data-test="project-color" class="size-[9px] shrink-0 rounded-[3px]" :class="{ 'opacity-40': !project.available }" :style="{ backgroundColor: project.color }" />
              <span class="flex min-w-0 grow flex-col">
                <span class="flex min-w-0 items-baseline gap-2">
                  <span data-test="project-name" class="truncate font-medium" :class="[showsBranch(project) ? 'max-w-[60%] shrink-0' : '', project.available ? 'text-fg' : 'text-fg-subtle']">{{ project.name }}</span>
                  <span
                    v-if="showsBranch(project)"
                    data-test="project-branch"
                    :title="repoLabel(git.reposFor(project.id)[0]!)"
                    class="min-w-0 truncate font-mono text-[0.6875rem] text-fg-subtle"
                  >{{ repoLabel(git.reposFor(project.id)[0]!) }}</span>
                </span>
                <span v-if="!project.available" class="text-xs text-fg-subtle">pasta indisponível</span>
                <span v-if="git.limitReached(project.id)" data-test="repo-limit" class="text-xs text-fg-muted">Só os 50 primeiros repositórios</span>
              </span>
              <span v-if="runningIn(project.id)" data-test="project-running" class="flex shrink-0 items-center">
                <DisplayStateIcon display="running" :size="11" /><span class="sr-only">em execução</span>
              </span>
              <span v-if="waitingIn(project.id)" data-test="project-waiting" class="flex shrink-0 items-center gap-1 text-xs font-semibold text-secondary">
                <DisplayStateIcon display="waiting" :size="11" />{{ waitingIn(project.id) }}<span class="sr-only"> aguardando você</span>
              </span>
            </RouterLink>
            <button
              v-if="hasChildren(project.id)"
              type="button"
              data-test="project-toggle"
              :aria-expanded="!isCollapsed('project', project.id)"
              :aria-label="`${isCollapsed('project', project.id) ? 'Expandir' : 'Recolher'} ${project.name}`"
              class="flex size-6 shrink-0 items-center justify-center rounded-md text-fg-subtle hover:bg-card hover:text-fg"
              @click="setCollapsed('project', project.id, !isCollapsed('project', project.id))"
            ><IconChevron :open="!isCollapsed('project', project.id)" :size="12" /></button>
          </div>
          <template v-if="!isCollapsed('project', project.id)">
            <div v-if="looseByProject.get(project.id)?.length" data-test="project-sessions" class="ml-[14px] flex flex-col gap-px border-l border-line pl-2">
              <SidebarSessionRow v-for="s in looseByProject.get(project.id)" :key="s.session_id" data-test="project-session" :session="s" hide-project nested />
            </div>
            <SidebarGroups v-if="groups.forProject(project.id).length" :project-id="project.id" />
          </template>
        </template>
      </section>

      <section v-if="split.others.length" aria-labelledby="sidebar-others-title" class="flex flex-col gap-px">
        <div class="flex h-[30px] items-center pl-2.5">
          <h2 id="sidebar-others-title" data-test="section-title" class="font-mono text-[0.6875rem] font-normal tracking-[0.08em] text-fg-subtle uppercase">Outros projetos</h2>
        </div>
        <button
          type="button"
          data-test="others-toggle"
          :aria-expanded="othersOpen"
          class="flex min-h-7 w-full items-center gap-1.5 rounded-md border-none bg-transparent px-2.5 text-left text-xs text-fg-subtle hover:text-fg focus-visible:outline-2 focus-visible:outline-primary"
          @click="toggleOthers"
        >
          <IconChevron :open="othersOpen" :size="12" />
          <span>{{ split.others.length }} sem conversa aberta</span>
        </button>
        <template v-if="othersOpen">
          <RouterLink
            v-for="project in split.others"
            :key="project.id"
            data-test="other-project"
            :data-available="String(project.available)"
            :to="{ name: 'project', params: { id: project.id } }"
            :class="[itemClass(activeProjectId === project.id), 'min-h-8 py-1']"
            :aria-current="route.name === 'project' && activeProjectId === project.id ? 'page' : undefined"
          >
            <span data-test="project-color" class="size-[9px] shrink-0 rounded-[3px]" :class="{ 'opacity-40': !project.available }" :style="{ backgroundColor: project.color }" />
            <span data-test="other-project-name" class="min-w-0 truncate" :class="[showsBranch(project) ? 'max-w-[60%] shrink-0' : '', project.available ? 'text-fg-muted' : 'text-fg-subtle']">{{ project.name }}</span>
            <span
              v-if="showsBranch(project)"
              data-test="other-project-branch"
              :title="repoLabel(git.reposFor(project.id)[0]!)"
              class="min-w-0 truncate font-mono text-[0.6875rem] text-fg-subtle"
            >{{ repoLabel(git.reposFor(project.id)[0]!) }}</span>
            <span v-if="!project.available" class="shrink-0 text-xs text-fg-subtle">pasta indisponível</span>
          </RouterLink>
        </template>
      </section>

      <SidebarLane lane="review" title="Para revisar" />
      <SidebarLane lane="later" title="Depois" start-collapsed />
    </div>

    <div class="flex h-12 shrink-0 items-center gap-1.5 border-t border-line px-2.5">
      <RouterLink to="/preferencias" data-test="preferences" :class="[itemClass(route.name === 'preferences'), 'grow']" :aria-current="route.name === 'preferences' ? 'page' : undefined">
        <IconSettings />Preferências
      </RouterLink>
      <span v-if="socket.status.value === 'connected'" data-test="connection-ok" class="flex shrink-0 items-center gap-1.5 pr-1.5 text-xs text-fg-subtle">
        <span class="size-[7px] rounded-full bg-primary" aria-hidden="true" />Conectado
      </span>
    </div>
    <div v-if="updates.state" data-test="app-version" class="flex min-w-0 shrink-0 items-center px-4 pb-2 font-mono text-xs text-fg-subtle">
      <button
        v-if="updates.showNotice"
        type="button"
        data-test="update-notice"
        class="min-w-0 cursor-pointer truncate rounded-sm border-none bg-transparent p-0 text-left font-mono text-xs text-fg-subtle hover:text-fg"
        :aria-label="`Versão ${updates.state.latest?.version} disponível. Você está na ${updates.state.current}.`"
        @click="updates.openModal()"
      >
        v{{ updates.state.current }} <span class="text-secondary">· {{ updates.state.latest?.version }} disponível</span>
      </button>
      <a
        v-else
        :href="`${updates.state.releases_url}/tag/v${updates.state.current}`"
        target="_blank"
        rel="noopener noreferrer"
        class="min-w-0 truncate text-fg-subtle no-underline hover:text-fg"
        :title="`Versão instalada: ${updates.state.current}`"
      >v{{ updates.state.current }}</a>
    </div>
    <ConnectionIndicator class="mx-2.5 mb-2.5" :status="socket.status.value" />
  </nav>
</template>
