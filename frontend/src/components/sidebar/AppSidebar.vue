<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import BrandMark from '../BrandMark.vue'
import ConnectionIndicator from '../ConnectionIndicator.vue'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import SessionSearch from './SessionSearch.vue'
import SidebarGroups from './SidebarGroups.vue'
import SidebarOpen from './SidebarOpen.vue'
import { sidebarItemClass } from './itemClass'
import { needsYou } from '../../conversation/needsYou'
import { useEventSocket } from '../../api/socket'
import { isCollapsed, setCollapsed } from '../../sidebarCollapse'
import { repoLabel, useGitStore } from '../../stores/git'
import { useGroupsStore } from '../../stores/groups'
import { useNewConversationStore } from '../../stores/newConversation'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import type { Session } from '../../types/api'
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
const route = useRoute()
const socket = useEventSocket()

// Only the waits that need you count; an ordinary wait with nothing new is not a reason to look.
const isWaitingOnYou = (s: Session) => s.display_state === 'waiting' && needsYou(s)
const waitingCount = computed(() => sessions.all.filter(isWaitingOnYou).length)
function waitingIn(projectId: number): number {
  return sessions.forProject(projectId).filter(isWaitingOnYou).length
}
function runningIn(projectId: number): boolean {
  return sessions.forProject(projectId).some((s) => s.display_state === 'running')
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
  <nav aria-label="Navegação" class="flex h-full w-[288px] shrink-0 flex-col border-r border-line bg-bg text-[13.5px]">
    <RouterLink to="/inbox" class="flex min-h-11 items-center gap-2 px-4 pt-3 pb-1.5 text-fg no-underline">
      <BrandMark />
      <span class="text-[15px] font-semibold tracking-tight">Cláudio Maestro</span>
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
        <kbd class="rounded border border-line-strong px-1.5 font-mono text-[11px] text-fg-subtle">C</kbd>
      </button>
      <SessionSearch />
    </div>

    <div class="flex flex-col gap-px px-2.5 pb-2">
      <RouterLink to="/inbox" data-test="nav-inbox" :class="itemClass(route.name === 'inbox')" :aria-current="route.name === 'inbox' ? 'page' : undefined">
        <IconInbox />
        <span class="grow">Inbox</span>
        <span v-if="waitingCount" class="flex shrink-0 items-center gap-1 text-xs font-semibold text-secondary">
          <DisplayStateIcon display="waiting" :size="11" /><span data-test="inbox-count">{{ waitingCount }}</span>
        </span>
      </RouterLink>
      <RouterLink to="/dashboard" data-test="nav-dashboard" :class="itemClass(route.name === 'dashboard')" :aria-current="route.name === 'dashboard' ? 'page' : undefined">
        <IconDashboard /><span class="grow">Dashboard</span>
      </RouterLink>
      <RouterLink to="/sessions" data-test="nav-conversations" :class="itemClass(route.name === 'sessions')" :aria-current="route.name === 'sessions' ? 'page' : undefined">
        <IconChat /><span class="grow">Conversas</span>
      </RouterLink>
    </div>

    <div class="flex min-h-0 flex-1 flex-col gap-px overflow-y-auto border-t border-line px-2.5 pt-1.5 pb-2">
      <div class="flex h-[30px] items-center pr-1 pl-2.5">
        <span class="grow font-mono text-[11px] tracking-[0.08em] text-fg-subtle uppercase">Projetos</span>
        <RouterLink to="/projects/new" data-test="new-project" aria-label="Novo projeto" class="flex size-[26px] items-center justify-center rounded-md text-fg-subtle no-underline hover:bg-card hover:text-fg"><IconPlus :size="13" /></RouterLink>
      </div>
      <p v-if="projects.loadError" class="px-2.5 py-2 text-xs text-diff-del-fg" role="alert">Não foi possível carregar os projetos. {{ projects.loadError }}</p>
      <p v-else-if="projects.loaded && projects.projects.length === 0" class="px-2.5 py-2 text-xs text-fg-muted">Nenhum projeto ainda.</p>
      <template v-for="project in projects.projects" :key="project.id">
        <div class="flex items-center">
          <button
            v-if="groups.forProject(project.id).length"
            type="button"
            data-test="project-toggle"
            :aria-expanded="!isCollapsed('project', project.id)"
            :aria-label="`${isCollapsed('project', project.id) ? 'Expandir' : 'Recolher'} ${project.name}`"
            class="flex size-5 shrink-0 items-center justify-center rounded-md text-fg-subtle hover:bg-card hover:text-fg"
            @click="setCollapsed('project', project.id, !isCollapsed('project', project.id))"
          ><IconChevron :open="!isCollapsed('project', project.id)" :size="12" /></button>
          <span v-else class="w-5 shrink-0" aria-hidden="true" />
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
                <span data-test="project-name" class="max-w-[60%] shrink-0 truncate font-medium" :class="project.available ? 'text-fg' : 'text-fg-subtle'">{{ project.name }}</span>
                <span
                  v-if="project.available && git.reposFor(project.id)[0]"
                  data-test="project-branch"
                  :title="repoLabel(git.reposFor(project.id)[0]!)"
                  class="min-w-0 truncate font-mono text-[11px] text-fg-subtle"
                >{{ repoLabel(git.reposFor(project.id)[0]!) }}</span>
              </span>
              <span v-if="!project.available" class="text-xs text-fg-subtle">pasta indisponível</span>
              <span v-if="git.limitReached(project.id)" data-test="repo-limit" class="text-xs text-fg-muted">Só os 50 primeiros repositórios</span>
            </span>
            <span v-if="runningIn(project.id)" data-test="project-running" class="flex shrink-0 items-center">
              <DisplayStateIcon display="running" :size="11" /><span class="sr-only">em execução</span>
            </span>
            <span v-if="waitingIn(project.id)" data-test="project-waiting" class="flex shrink-0 items-center gap-1 text-xs font-semibold text-secondary">
              <DisplayStateIcon display="waiting" :size="11" />{{ waitingIn(project.id) }}
            </span>
          </RouterLink>
        </div>
        <SidebarGroups v-if="groups.forProject(project.id).length && !isCollapsed('project', project.id)" :project-id="project.id" />
      </template>

      <SidebarOpen />
    </div>

    <div class="flex h-12 shrink-0 items-center gap-1.5 border-t border-line px-2.5">
      <RouterLink to="/preferencias" data-test="preferences" :class="[itemClass(route.name === 'preferences'), 'grow']" :aria-current="route.name === 'preferences' ? 'page' : undefined">
        <IconSettings />Preferências
      </RouterLink>
      <span v-if="socket.status.value === 'connected'" data-test="connection-ok" class="flex shrink-0 items-center gap-1.5 pr-1.5 text-xs text-fg-subtle">
        <span class="size-[7px] rounded-full bg-primary" aria-hidden="true" />Conectado
      </span>
    </div>
    <ConnectionIndicator class="mx-2.5 mb-2.5" :status="socket.status.value" />
  </nav>
</template>
