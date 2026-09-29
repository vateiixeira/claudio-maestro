<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import SessionGroup from '../components/session/SessionGroup.vue'
import { errorMessage } from '../api/http'
import { displayStateLabels } from '../sessionState'
import { useProjectsStore } from '../stores/projects'
import { useSessionsStore } from '../stores/sessions'
import type { DisplayState } from '../types/api'

const projects = useProjectsStore()
const sessions = useSessionsStore()

// null shows every project.
const projectFilter = ref<number | null>(null)
const error = ref<string | null>(null)

onMounted(async () => {
  try {
    if (!projects.loaded) await projects.load()
    await sessions.loadAll(projects.projects.map((p) => p.id))
  } catch (e) {
    error.value = errorMessage(e)
  }
})

const visible = computed(() =>
  projectFilter.value == null ? sessions.all : sessions.all.filter((s) => s.project_id === projectFilter.value),
)

const columns = computed(() =>
  (['running', 'waiting', 'finished'] as DisplayState[]).map((display) => ({
    display,
    title: display === 'finished' ? 'Finalizadas' : displayStateLabels[display],
    sessions: visible.value.filter((s) => s.display_state === display),
  })),
)

const filterClass = (active: boolean) =>
  active ? 'border-fg-muted bg-elevated text-fg' : 'border-line text-fg-muted hover:bg-card hover:text-fg'
</script>

<template>
  <div class="flex h-full flex-col gap-5 px-8 py-7">
    <header class="flex flex-wrap items-center gap-4">
      <h1 class="m-0 grow text-[28px] font-semibold tracking-tight">Todas as sessões</h1>
      <div class="flex flex-wrap gap-2" role="group" aria-label="Filtrar por projeto">
        <button
          type="button"
          data-test="filter"
          class="h-11 rounded-lg border px-3.5 text-sm font-medium"
          :class="filterClass(projectFilter == null)"
          :aria-pressed="projectFilter == null"
          @click="projectFilter = null"
        >
          Todos os projetos
        </button>
        <button
          v-for="project in projects.projects"
          :key="project.id"
          type="button"
          data-test="filter"
          class="flex h-11 items-center gap-2 rounded-lg border px-3.5 text-sm font-medium"
          :class="filterClass(projectFilter === project.id)"
          :aria-pressed="projectFilter === project.id"
          @click="projectFilter = project.id"
        >
          <span class="size-2.5 rounded-[3px]" :style="{ backgroundColor: project.color }" />
          {{ project.name }}
        </button>
      </div>
    </header>

    <p v-if="error" role="alert" class="m-0 rounded-lg border border-secondary/40 bg-card px-4 py-3 text-sm text-secondary-soft">
      {{ error }}
    </p>

    <div class="grid min-h-0 grow grid-cols-1 gap-4 lg:grid-cols-3">
      <div
        v-for="column in columns"
        :key="column.display"
        :data-test="`column-${column.display}`"
        class="flex min-h-0 flex-col overflow-y-auto rounded-lg border border-line bg-panel p-4"
      >
        <SessionGroup
          :display="column.display"
          :title="column.title"
          :sessions="column.sessions"
          show-project
          @error="error = $event"
        >
          <template #empty>
            <p class="m-0 text-sm text-fg-muted">Nenhuma sessão aqui.</p>
          </template>
        </SessionGroup>
      </div>
    </div>
  </div>
</template>
