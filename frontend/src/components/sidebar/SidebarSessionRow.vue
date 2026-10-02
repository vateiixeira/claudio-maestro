<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import { isQuietSession, sidebarItemClass } from './itemClass'
import { useProjectsStore } from '../../stores/projects'
import { worktreeLabel } from '../../worktree'
import type { Session } from '../../types/api'

const props = defineProps<{ session: Session }>()
const route = useRoute()
const projects = useProjectsStore()
const project = computed(() => projects.byId(props.session.project_id))
const worktree = computed(() => worktreeLabel(props.session))
const active = computed(() => route.name === 'session' && route.params.id === props.session.session_id)
</script>

<template>
  <RouterLink
    :to="{ name: 'session', params: { id: session.session_id } }"
    :class="sidebarItemClass(active)"
    :aria-current="active ? 'page' : undefined"
  >
    <DisplayStateIcon :display="session.display_state" :size="11" :quiet="isQuietSession(session)" />
    <span data-test="row-title" class="min-w-0 grow truncate text-[13px]">{{ session.title }}</span>
    <span
      v-if="project"
      data-test="row-project"
      :title="project.name"
      class="size-2 shrink-0 rounded-[2px]"
      :style="{ backgroundColor: project.color }"
    ><span class="sr-only">{{ project.name }}</span></span>
    <span v-if="worktree" data-test="row-worktree" :title="worktree" :aria-label="worktree" class="shrink-0 text-fg-muted">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /><path d="M6.5 10v4a3 3 0 0 0 3 3H14" />
      </svg>
    </span>
  </RouterLink>
</template>
