<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import BrandMark from '../BrandMark.vue'
import ConnectionIndicator from '../ConnectionIndicator.vue'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import SessionSearch from './SessionSearch.vue'
import SidebarGroups from './SidebarGroups.vue'
import BranchLabel from '../git/BranchLabel.vue'
import { useEventSocket } from '../../api/socket'
import { recentIds } from '../../recentConversations'
import { isCollapsed, setCollapsed } from '../../sidebarCollapse'
import { repoLabel, useGitStore } from '../../stores/git'
import { useGroupsStore } from '../../stores/groups'
import { useNewConversationStore } from '../../stores/newConversation'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'

const projects = useProjectsStore()
const sessions = useSessionsStore()
const git = useGitStore()
const groups = useGroupsStore()
const newConversation = useNewConversationStore()
const route = useRoute()
const socket = useEventSocket()

const waitingCount = computed(() => sessions.all.filter((s) => s.display_state === 'waiting').length)
function waitingIn(projectId: number): number {
  return sessions.forProject(projectId).filter((s) => s.display_state === 'waiting').length
}
// Conversations the user opened (not just marked as read), most recently opened first.
const recent = computed(() =>
  recentIds.value
    .map((id) => sessions.find(id))
    .filter((s): s is NonNullable<typeof s> => s != null)
    .slice(0, 5),
)
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
const itemClass = (active: boolean) => [
  'flex min-h-10 items-center gap-2.5 rounded-lg px-3 no-underline hover:bg-card',
  active ? 'bg-elevated text-fg' : 'text-fg-muted hover:text-fg',
]
</script>

<template>
  <nav aria-label="Navegação" class="flex h-full w-64 shrink-0 flex-col gap-3 border-r border-line bg-panel px-3 pt-5 pb-3 text-sm">
    <RouterLink to="/inbox" class="flex min-h-11 items-center gap-2.5 rounded-lg px-2 text-fg no-underline">
      <BrandMark />
      <span class="text-xl font-bold tracking-tight">Vini7 Vibing</span>
    </RouterLink>

    <div class="flex flex-col gap-0.5">
      <button type="button" data-test="nav-new" :class="itemClass(false)" class="w-full text-left" @click="newConversation.open(currentProjectId, currentGroupId)">
        <span aria-hidden="true">＋</span><span class="grow">Nova conversa</span><kbd class="font-mono text-[11px] text-fg-muted">C</kbd>
      </button>
      <SessionSearch />
      <RouterLink to="/dashboard" data-test="nav-dashboard" :class="itemClass(route.name === 'dashboard')" :aria-current="route.name === 'dashboard' ? 'page' : undefined">Dashboard</RouterLink>
      <RouterLink to="/inbox" data-test="nav-inbox" :class="itemClass(route.name === 'inbox')" :aria-current="route.name === 'inbox' ? 'page' : undefined">
        <span class="grow">Inbox</span>
        <span v-if="waitingCount" data-test="inbox-count" class="rounded-full bg-secondary px-2 text-xs font-semibold text-secondary-fg">{{ waitingCount }}</span>
      </RouterLink>
      <RouterLink to="/sessions" data-test="nav-conversations" :class="itemClass(route.name === 'sessions')" :aria-current="route.name === 'sessions' ? 'page' : undefined">Conversas</RouterLink>
    </div>

    <div class="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto">
      <div class="flex items-center px-3 pt-2 pb-0.5">
        <span class="grow font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Projetos</span>
        <RouterLink to="/projects/new" data-test="new-project" aria-label="Novo projeto" class="flex size-7 items-center justify-center rounded-md text-fg-muted no-underline hover:bg-card hover:text-fg">＋</RouterLink>
      </div>
      <p v-if="projects.loadError" class="px-3 py-2 text-xs text-secondary-soft" role="alert">Não foi possível carregar os projetos. {{ projects.loadError }}</p>
      <p v-else-if="projects.loaded && projects.projects.length === 0" class="px-3 py-2 text-xs text-fg-muted">Nenhum projeto ainda.</p>
      <template v-for="project in projects.projects" :key="project.id">
        <div class="flex items-center">
          <button
            v-if="groups.forProject(project.id).length"
            type="button"
            data-test="project-toggle"
            :aria-expanded="!isCollapsed('project', project.id)"
            :aria-label="`${isCollapsed('project', project.id) ? 'Expandir' : 'Recolher'} ${project.name}`"
            class="flex size-6 shrink-0 items-center justify-center rounded-md text-fg-muted hover:bg-card hover:text-fg"
            @click="setCollapsed('project', project.id, !isCollapsed('project', project.id))"
          ><span aria-hidden="true" class="inline-block transition-transform" :class="isCollapsed('project', project.id) ? '' : 'rotate-90'">›</span></button>
          <span v-else class="size-6 shrink-0" aria-hidden="true" />
          <RouterLink
            data-test="project"
            :data-available="String(project.available)"
            :to="{ name: 'project', params: { id: project.id } }"
            :class="[itemClass(activeProjectId === project.id), 'min-w-0 grow', { 'opacity-50': !project.available }]"
            :aria-current="route.name === 'project' && activeProjectId === project.id ? 'page' : undefined"
          >
            <span data-test="project-color" class="size-2.5 shrink-0 rounded-[3px]" :style="{ backgroundColor: project.color }" />
            <span class="flex min-w-0 grow flex-col">
              <span data-test="project-name" class="truncate font-medium text-fg">{{ project.name }}</span>
              <span v-if="!project.available" class="text-xs">pasta indisponível</span>
              <span v-else-if="git.reposFor(project.id)[0]" data-test="project-branch"><BranchLabel :text="repoLabel(git.reposFor(project.id)[0]!)" muted /></span>
              <span v-if="git.limitReached(project.id)" data-test="repo-limit" class="text-xs text-secondary-soft">Só os 50 primeiros repositórios</span>
            </span>
            <span v-if="waitingIn(project.id)" data-test="project-waiting" class="flex items-center gap-1 text-xs text-secondary">
              <DisplayStateIcon display="waiting" :size="11" />{{ waitingIn(project.id) }}
            </span>
          </RouterLink>
        </div>
        <SidebarGroups v-if="groups.forProject(project.id).length && !isCollapsed('project', project.id)" :project-id="project.id" />
      </template>

      <template v-if="recent.length">
        <div class="px-3 pt-4 pb-0.5 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Recentes</div>
        <RouterLink
          v-for="session in recent"
          :key="session.session_id"
          data-test="recent"
          :to="{ name: 'session', params: { id: session.session_id } }"
          :class="itemClass(route.name === 'session' && route.params.id === session.session_id)"
          :aria-current="route.name === 'session' && route.params.id === session.session_id ? 'page' : undefined"
        >
          <DisplayStateIcon :display="session.display_state" :size="11" />
          <span class="min-w-0 grow truncate text-[13px]">{{ session.title }}</span>
        </RouterLink>
      </template>
    </div>

    <RouterLink to="/preferencias" data-test="preferences" :class="itemClass(route.name === 'preferences')" :aria-current="route.name === 'preferences' ? 'page' : undefined">Preferências</RouterLink>
    <ConnectionIndicator :status="socket.status.value" />
  </nav>
</template>
