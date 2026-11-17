<script setup lang="ts">
import { computed, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import BrandMark from '../BrandMark.vue'
import ConnectionIndicator from '../ConnectionIndicator.vue'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import FilterChip from '../ui/FilterChip.vue'
import SessionSearch from './SessionSearch.vue'
import SidebarAgents from './SidebarAgents.vue'
import SidebarGroups from './SidebarGroups.vue'
import SidebarLane from './SidebarLane.vue'
import SidebarSessionRow from './SidebarSessionRow.vue'
import UsageMeter from './UsageMeter.vue'
import AgentdNotice from '../updates/AgentdNotice.vue'
import ClaudeUpdateNotice from '../updates/ClaudeUpdateNotice.vue'
import UpdatedNotice from '../updates/UpdatedNotice.vue'
import { looseOpenSessions } from './openList'
import { sidebarItemClass } from './itemClass'
import { isActive } from '../../groupList'
import { isDiscarded } from '../../conversation/marks'
import { needsYou } from '../../conversation/needsYou'
import { useEventSocket } from '../../api/socket'
import { isCollapsed, isSectionOpened, setCollapsed, setSectionOpened } from '../../sidebarCollapse'
import { behindCount, behindSrText, behindTitle } from '../../gitSync'
import { useMinuteClock } from '../../minuteClock'
import { matchesSidebarFilter, sidebarFilter, sidebarFilterLabel, type SidebarFilter } from '../../sidebarFilter'
import { filteredProjectTree, splitProjects } from '../../sidebarTree'
import { SIDEBAR_DEFAULT_WIDTH, SIDEBAR_KEY_STEP, SIDEBAR_MAX_WIDTH, SIDEBAR_MIN_WIDTH, clampSidebarWidth, sidebarWidth, writeSidebarWidth } from '../../sidebarWidthPref'
import { repoLabel, useGitStore } from '../../stores/git'
import { useGroupsStore } from '../../stores/groups'
import { useNewConversationStore } from '../../stores/newConversation'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import { useOrgStore } from '../../stores/org'
import { useTasksStore } from '../../stores/tasks'
import { useUpdatesStore } from '../../stores/updates'
import type { GitRepo, Project, Session, SessionGroup } from '../../types/api'
import IconAgents from '../icons/IconAgents.vue'
import IconArrowDown from '../icons/IconArrowDown.vue'
import IconChat from '../icons/IconChat.vue'
import IconChevron from '../icons/IconChevron.vue'
import IconDashboard from '../icons/IconDashboard.vue'
import IconDeliveries from '../icons/IconDeliveries.vue'
import IconInbox from '../icons/IconInbox.vue'
import IconPlus from '../icons/IconPlus.vue'
import IconSettings from '../icons/IconSettings.vue'

const projects = useProjectsStore()
const sessions = useSessionsStore()
const org = useOrgStore()
const tasks = useTasksStore()
const git = useGitStore()
const groups = useGroupsStore()
const newConversation = useNewConversationStore()
const updates = useUpdatesStore()
const route = useRoute()
const socket = useEventSocket()
const now = useMinuteClock()

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
const isWaitingOnYou = (s: Session) => s.display_state === 'waiting' && needsYou(s) && !isDiscarded(s)
const waitingCount = computed(() => sessions.all.filter(isWaitingOnYou).length)
// The agents' sessions are listed (and counted) in the "Agentes" section, not under their project.
const isOrdinary = (s: Session) => s.agent_id == null
function waitingIn(projectId: number): number {
  return sessions.forProject(projectId).filter((s) => isOrdinary(s) && isWaitingOnYou(s)).length
}
function runningIn(projectId: number): number {
  return sessions.forProject(projectId).filter((s) => isOrdinary(s) && s.display_state === 'running' && !isDiscarded(s)).length
}

// The chips above the projects: what the sidebar lists (open, not an agent's, not discarded) that each filter keeps.
const FILTERS: SidebarFilter[] = ['running', 'waiting', 'unread']
const filterCounts = computed<Record<SidebarFilter, number>>(() => {
  const counts = { running: 0, waiting: 0, unread: 0 }
  for (const s of sessions.all) {
    if (!isOrdinary(s) || !isActive(s)) continue
    for (const f of FILTERS) if (matchesSidebarFilter(s, f)) counts[f]++
  }
  return counts
})
const shownFilters = computed(() => FILTERS.filter((f) => filterCounts.value[f] > 0))
function toggleFilter(filter: SidebarFilter) {
  sidebarFilter.value = sidebarFilter.value === filter ? null : filter
}
// Nothing left for the filter on (the conversation was answered): it turns itself off and the list comes back whole.
// The watcher runs before the render of the same update, so the list is never drawn empty.
watch(filterCounts, (counts) => {
  if (sidebarFilter.value && counts[sidebarFilter.value] === 0) sidebarFilter.value = null
})
// Groups under each project: those created in it and those holding one of its conversations.
const groupsByProject = computed(() => {
  const map = new Map<number, SessionGroup[]>()
  for (const p of projects.projects) map.set(p.id, groups.visibleIn(p.id, sessions.all))
  return map
})
// The ones the sidebar actually lists: a group without a listed conversation (open and matching the filter) is hidden,
// so it does not count as a child.
const listedGroupsByProject = computed(() => {
  const map = new Map<number, number>()
  for (const [id, list] of groupsByProject.value) map.set(id, filteredProjectTree(list, sessions.all, sidebarFilter.value).length)
  return map
})
// Open conversations of each project outside its groups that match the filter, the ones waiting for you first;
// grouped ones show under their group. Built once per change so the template reads it instead of recomputing per project.
const looseByProject = computed(() => {
  const map = new Map<number, Session[]>()
  for (const p of projects.projects) {
    const loose = looseOpenSessions(sessions.all, p.id, new Set((groupsByProject.value.get(p.id) ?? []).map((g) => g.id)))
    map.set(p.id, loose.filter((s) => matchesSidebarFilter(s, sidebarFilter.value)))
  }
  return map
})
function hasChildren(projectId: number): boolean {
  return (listedGroupsByProject.value.get(projectId) ?? 0) > 0 || (looseByProject.value.get(projectId)?.length ?? 0) > 0
}
// "Conversas abertas": projects with an open conversation. "Outros projetos": the rest, kept in one folded line.
const split = computed(() => splitProjects(projects.projects, sessions.all))
// With a filter on, a collapsed project still shows the conversations that match: they are what was asked for.
const projectOpen = (id: number) => sidebarFilter.value !== null || !isCollapsed('project', id)
// With a filter on, the projects with no conversation that matches leave the list; the one on screen stays, so you can tell where you are.
const listedActive = computed(() =>
  sidebarFilter.value === null ? split.value.active : split.value.active.filter((p) => p.id === activeProjectId.value || hasChildren(p.id)),
)
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
// The repository shown next to the project name, when the remote has commits to pull.
function behindRepo(project: Project): GitRepo | undefined {
  const repo = showsBranch(project) ? git.reposFor(project.id)[0] : undefined
  return repo && behindCount(repo) > 0 ? repo : undefined
}
// The project being looked at, directly or through one of its conversations.
const activeProjectId = computed<number | null>(() => {
  if (route.name === 'project') return Number(route.params.id)
  if (route.name === 'agents') return Number(route.params.projectId) || null
  if (route.name === 'tasks') return Number(route.query.project) || null
  if (route.name === 'task') return tasks.details[Number(route.params.id)]?.task.project_id ?? null
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
    <RouterLink to="/inicio" class="flex min-h-11 items-center gap-2 px-4 pt-3 pb-1.5 text-fg no-underline">
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
      <RouterLink to="/inicio" data-test="nav-start" :class="itemClass(route.name === 'start')" :aria-current="route.name === 'start' ? 'page' : undefined"><IconInbox /><span class="grow">Início</span></RouterLink>
      <RouterLink to="/tarefas" data-test="nav-tasks" :class="itemClass(route.name === 'tasks' || route.name === 'task')" :aria-current="route.name === 'tasks' || route.name === 'task' ? 'page' : undefined"><IconDeliveries /><span class="grow">Tarefas</span></RouterLink>
      <RouterLink to="/agentes" data-test="nav-agents" :class="itemClass(route.name === 'agents')" :aria-current="route.name === 'agents' ? 'page' : undefined">
        <IconAgents /><span class="grow">Agentes</span>
        <span v-if="org.unreadCount" data-test="agents-count" class="flex shrink-0 items-center gap-1 text-xs font-semibold text-secondary">
          <span aria-hidden="true">{{ org.unreadCount }}</span><span class="sr-only">{{ org.unreadCount }} {{ org.unreadCount === 1 ? 'aviso não lido' : 'avisos não lidos' }}</span>
        </span>
      </RouterLink>
      <RouterLink to="/projects" data-test="nav-projects" :class="itemClass(route.name === 'projects' || route.name === 'project-new')" :aria-current="route.name === 'projects' ? 'page' : undefined"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /></svg><span class="grow">Projetos</span></RouterLink>
      <details class="mt-2 text-fg-muted"><summary class="cursor-pointer px-2.5 py-2 text-xs text-fg-subtle">Mais ferramentas</summary>
      <RouterLink :to="waitingCount ? '/inbox?aba=pede-voce' : '/inbox'" data-test="nav-inbox" :class="itemClass(route.name === 'inbox')" :aria-current="route.name === 'inbox' ? 'page' : undefined">
        <IconInbox />
        <span class="grow">Inbox</span>
        <span v-if="waitingCount" class="flex shrink-0 items-center gap-1 text-xs font-semibold text-secondary">
          <DisplayStateIcon display="waiting" :size="11" /><span data-test="inbox-count">{{ waitingCount }}</span><span class="sr-only"> aguardando você</span>
        </span>
      </RouterLink>
      <RouterLink to="/dashboard" data-test="nav-dashboard" :class="itemClass(route.name === 'dashboard')" :aria-current="route.name === 'dashboard' ? 'page' : undefined">
        <IconDashboard /><span class="grow">Painel</span>
      </RouterLink>
      <RouterLink to="/sessions" data-test="nav-conversations" :class="itemClass(route.name === 'sessions')" :aria-current="route.name === 'sessions' ? 'page' : undefined">
        <IconChat /><span class="grow">Conversas</span>
      </RouterLink>
      <RouterLink to="/entregas" data-test="nav-deliveries" :class="itemClass(route.name === 'deliveries')" :aria-current="route.name === 'deliveries' ? 'page' : undefined">
        <IconDeliveries /><span class="grow">Entregas</span>
      </RouterLink>
      </details>
    </div>

    <div data-test="sidebar-sections" class="relative flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-2.5 pt-3.5 pb-2">
      <SidebarAgents />

      <section aria-labelledby="sidebar-active-title" class="flex flex-col gap-px">
        <div class="flex h-[30px] items-center pr-1 pl-2.5">
          <h2 id="sidebar-active-title" data-test="section-title" class="grow font-mono text-[0.6875rem] font-normal tracking-[0.08em] text-fg-subtle uppercase">Conversas abertas</h2>
          <RouterLink to="/projects/new" data-test="new-project" aria-label="Novo projeto" class="flex size-[26px] items-center justify-center rounded-md text-fg-subtle no-underline hover:bg-card hover:text-fg"><IconPlus :size="13" /></RouterLink>
        </div>
        <div v-if="shownFilters.length" data-test="sidebar-filters" role="group" aria-label="Filtrar conversas abertas" class="flex flex-wrap gap-1.5 pt-1 pr-1 pb-2.5 pl-1">
          <FilterChip
            v-for="f in shownFilters"
            :key="f"
            data-test="sidebar-filter"
            :data-filter="f"
            :label="sidebarFilterLabel(f, filterCounts[f])"
            :pressed="sidebarFilter === f"
            @toggle="toggleFilter(f)"
          >
            <template #icon>
              <span v-if="f === 'unread'" class="size-[7px] shrink-0 rounded-full bg-fg" aria-hidden="true" />
              <DisplayStateIcon v-else :display="f" :size="12" />
            </template>
          </FilterChip>
        </div>
        <p v-if="projects.loadError" class="px-2.5 py-2 text-xs text-diff-del-fg" role="alert">Não foi possível carregar os projetos. {{ projects.loadError }}</p>
        <p v-else-if="projects.loaded && projects.regular.length === 0" class="px-2.5 py-2 text-xs text-fg-muted">Nenhum projeto ainda.</p>
        <p v-else-if="projects.projects.length > 0 && split.active.length === 0" data-test="no-open" class="px-2.5 py-1 text-xs text-fg-subtle">Nenhuma conversa aberta</p>
        <template v-for="(project, index) in listedActive" :key="project.id">
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
                  <span data-test="project-name" :title="project.name" class="min-w-0 shrink-[0.2] truncate font-medium" :class="project.available ? 'text-fg' : 'text-fg-subtle'">{{ project.name }}</span>
                  <span
                    v-if="showsBranch(project)"
                    data-test="project-branch"
                    :title="repoLabel(git.reposFor(project.id)[0]!)"
                    class="min-w-0 truncate font-mono text-[0.6875rem] text-fg-subtle"
                  >{{ repoLabel(git.reposFor(project.id)[0]!) }}</span>
                  <span
                    v-if="behindRepo(project)"
                    data-test="project-behind"
                    :title="behindTitle(behindRepo(project)!, now)"
                    class="inline-flex shrink-0 items-center self-center text-secondary-soft"
                  ><IconArrowDown :size="10" :stroke-width="2.6" /><span class="sr-only">{{ behindSrText(behindRepo(project)!) }}</span></span>
                </span>
                <span v-if="!project.available" class="text-xs text-fg-subtle">pasta indisponível</span>
                <span v-if="git.limitReached(project.id)" data-test="repo-limit" class="text-xs text-fg-muted">Só os 50 primeiros repositórios</span>
              </span>
              <span v-if="runningIn(project.id)" data-test="project-running" class="flex shrink-0 items-center gap-1 text-xs font-semibold text-primary-soft">
                <DisplayStateIcon display="running" :size="11" /><span data-test="project-running-count">{{ runningIn(project.id) }}</span><span class="sr-only"> em execução</span>
              </span>
              <span v-if="waitingIn(project.id)" data-test="project-waiting" class="flex shrink-0 items-center gap-1 text-xs font-semibold text-secondary">
                <DisplayStateIcon display="waiting" :size="11" />{{ waitingIn(project.id) }}<span class="sr-only"> aguardando você</span>
              </span>
            </RouterLink>
            <button
              v-if="hasChildren(project.id)"
              type="button"
              data-test="project-toggle"
              :aria-expanded="projectOpen(project.id)"
              :disabled="sidebarFilter !== null"
              :aria-label="`${projectOpen(project.id) ? 'Recolher' : 'Expandir'} ${project.name}`"
              class="flex size-6 shrink-0 items-center justify-center rounded-md text-fg-subtle hover:bg-card hover:text-fg disabled:cursor-default disabled:opacity-50 disabled:hover:bg-transparent disabled:hover:text-fg-subtle"
              @click="setCollapsed('project', project.id, !isCollapsed('project', project.id))"
            ><IconChevron :open="projectOpen(project.id)" :size="12" /></button>
          </div>
          <template v-if="projectOpen(project.id)">
            <div v-if="looseByProject.get(project.id)?.length" data-test="project-sessions" class="ml-[14px] flex flex-col gap-px border-l border-line pl-2">
              <SidebarSessionRow v-for="s in looseByProject.get(project.id)" :key="s.session_id" data-test="project-session" :session="s" hide-project nested />
            </div>
            <SidebarGroups v-if="listedGroupsByProject.get(project.id)" :project-id="project.id" />
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
            <span class="flex min-w-0 grow flex-col">
              <span data-test="other-project-name" :title="project.name" class="min-w-0 truncate" :class="project.available ? 'text-fg-muted' : 'text-fg-subtle'">{{ project.name }}</span>
              <span v-if="showsBranch(project)" class="flex min-w-0 items-baseline gap-2">
                <span
                  data-test="other-project-branch"
                  :title="repoLabel(git.reposFor(project.id)[0]!)"
                  class="min-w-0 truncate font-mono text-[0.6875rem] text-fg-subtle"
                >{{ repoLabel(git.reposFor(project.id)[0]!) }}</span>
                <span
                  v-if="behindRepo(project)"
                  data-test="project-behind"
                  :title="behindTitle(behindRepo(project)!, now)"
                  class="inline-flex shrink-0 items-center self-center text-secondary-soft"
                ><IconArrowDown :size="10" :stroke-width="2.6" /><span class="sr-only">{{ behindSrText(behindRepo(project)!) }}</span></span>
              </span>
              <span v-if="!project.available" class="text-xs text-fg-subtle">pasta indisponível</span>
            </span>
          </RouterLink>
        </template>
      </section>

      <SidebarLane lane="review" title="Para revisar" />
      <SidebarLane lane="later" title="Depois" start-collapsed />
    </div>

    <UsageMeter />
    <div class="flex h-12 shrink-0 items-center gap-1.5 border-t border-line px-2.5">
      <RouterLink to="/preferencias" data-test="preferences" :class="[itemClass(route.name === 'preferences'), 'grow']" :aria-current="route.name === 'preferences' ? 'page' : undefined">
        <IconSettings />Preferências
      </RouterLink>
      <span v-if="socket.status.value === 'connected'" data-test="connection-ok" class="flex shrink-0 items-center gap-1.5 pr-1.5 text-xs text-fg-subtle">
        <span class="size-[7px] rounded-full bg-primary" aria-hidden="true" />Conectado
      </span>
    </div>
    <UpdatedNotice />
    <AgentdNotice />
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
    <ClaudeUpdateNotice />
    <ConnectionIndicator class="mx-2.5 mb-2.5" :status="socket.status.value" />
  </nav>
</template>
