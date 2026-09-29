<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import BrandMark from '../BrandMark.vue'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import StateCounters from '../StateCounters.vue'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import { displayStateLabels } from '../../sessionState'
import type { Session } from '../../types/api'

const projects = useProjectsStore()
const sessions = useSessionsStore()
const route = useRoute()

// The project being looked at, directly or through one of its sessions.
const activeProjectId = computed<number | null>(() => {
  if (route.name === 'project') return Number(route.params.id)
  if (route.name === 'session') return sessions.find(String(route.params.id))?.project_id ?? null
  return null
})

const activeSessionId = computed(() => (route.name === 'session' ? String(route.params.id) : null))

// The menu lists only what is alive: finished sessions stay on the project page.
function openSessions(projectId: number): Session[] {
  return sessions.forProject(projectId).filter((s) => s.display_state !== 'finished')
}

function count(list: Session[], display: 'running' | 'waiting'): number {
  return list.filter((s) => s.display_state === display).length
}

function sessionTone(session: Session): string {
  return session.awaiting_decision ? 'text-secondary-soft' : 'text-fg'
}
</script>

<template>
  <nav
    aria-label="Projetos e sessões"
    class="flex h-full w-72 shrink-0 flex-col gap-3.5 border-r border-line bg-panel px-3 pt-5 pb-3 text-sm"
  >
    <RouterLink to="/" class="flex min-h-11 items-center gap-2.5 rounded-lg px-2 text-fg no-underline">
      <BrandMark />
      <span class="text-xl font-bold tracking-tight">Vini7 Vibing</span>
    </RouterLink>

    <RouterLink
      to="/sessions"
      data-test="all-sessions"
      class="flex min-h-11 items-center gap-2.5 rounded-lg border px-3 text-fg no-underline hover:bg-card"
      :class="route.name === 'sessions' ? 'border-line-strong bg-elevated' : 'border-line'"
      :aria-current="route.name === 'sessions' ? 'page' : undefined"
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <rect x="3" y="4" width="5" height="16" rx="1" />
        <rect x="10" y="4" width="5" height="10" rx="1" />
        <rect x="17" y="4" width="4" height="13" rx="1" />
      </svg>
      <span class="grow font-medium">Todas as sessões</span>
      <StateCounters :running="count(sessions.all, 'running')" :waiting="count(sessions.all, 'waiting')" />
    </RouterLink>

    <div class="flex min-h-0 flex-1 flex-col gap-1">
      <div class="px-3 pb-0.5 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Projetos</div>

      <div class="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto">
        <p v-if="projects.loadError" class="px-3 py-2 text-xs text-secondary-soft" role="alert">
          Não foi possível carregar os projetos. {{ projects.loadError }}
        </p>
        <p v-else-if="projects.loaded && projects.projects.length === 0" class="px-3 py-2 text-xs text-fg-muted">
          Nenhum projeto ainda.
        </p>

        <div
          v-for="project in projects.projects"
          :key="project.id"
          data-test="project"
          :data-available="String(project.available)"
          class="flex flex-col gap-1 rounded-lg border px-3 py-1.5"
          :class="activeProjectId === project.id ? 'border-line-strong bg-elevated' : 'border-transparent'"
        >
          <RouterLink
            :to="{ name: 'project', params: { id: project.id } }"
            class="flex min-h-11 items-center gap-2.5 text-fg no-underline"
            :class="{ 'opacity-50': !project.available }"
            :aria-current="route.name === 'project' && activeProjectId === project.id ? 'page' : undefined"
          >
            <span
              data-test="project-color"
              class="size-2.5 shrink-0 rounded-[3px]"
              :style="{ backgroundColor: project.color }"
            />
            <span class="flex min-w-0 flex-1 flex-col">
              <span data-test="project-name" class="truncate font-semibold">{{ project.name }}</span>
              <span v-if="!project.available" class="text-xs text-fg-muted">pasta indisponível</span>
            </span>
            <StateCounters
              :running="count(openSessions(project.id), 'running')"
              :waiting="count(openSessions(project.id), 'waiting')"
            />
          </RouterLink>

          <div
            v-if="openSessions(project.id).length > 0"
            class="flex flex-col border-t border-line pt-1"
          >
            <RouterLink
              v-for="session in openSessions(project.id)"
              :key="session.session_id"
              data-test="session"
              :to="{ name: 'session', params: { id: session.session_id } }"
              class="flex min-h-11 items-center gap-2 rounded-md px-1 no-underline hover:bg-card"
              :data-unread="String(session.unread)"
              :class="[sessionTone(session), { 'bg-card': activeSessionId === session.session_id, 'font-semibold': session.unread }]"
              :title="`${session.title} · ${displayStateLabels[session.display_state]}`"
              :aria-current="activeSessionId === session.session_id ? 'page' : undefined"
            >
              <DisplayStateIcon :display="session.display_state" />
              <span class="min-w-0 flex-1 truncate text-[13px]">{{ session.title }}</span>
              <span v-if="session.unread" class="size-1.5 shrink-0 rounded-full bg-primary-soft" aria-hidden="true" />
              <span class="sr-only">
                {{ displayStateLabels[session.display_state] }}{{ session.unread ? ', com novidade' : '' }}
              </span>
            </RouterLink>
          </div>
        </div>
      </div>
    </div>

    <RouterLink
      to="/projects/new"
      data-test="new-project"
      class="flex min-h-11 items-center justify-center gap-2 rounded-lg border border-dashed border-line-strong font-medium text-fg no-underline hover:bg-card"
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
        <line x1="12" y1="5" x2="12" y2="19" />
        <line x1="5" y1="12" x2="19" y2="12" />
      </svg>
      Novo projeto
    </RouterLink>
  </nav>
</template>
