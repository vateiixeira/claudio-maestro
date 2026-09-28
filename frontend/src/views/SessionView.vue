<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import SessionStateIcon from '../components/SessionStateIcon.vue'
import { sessionStateLabels } from '../sessionState'
import { useProjectsStore } from '../stores/projects'
import { useSessionsStore } from '../stores/sessions'

// Placeholder: the conversation column comes in the next task.
const props = defineProps<{ id: string }>()

const sessions = useSessionsStore()
const projects = useProjectsStore()

const session = computed(() => sessions.find(props.id))
const project = computed(() => (session.value ? projects.byId(session.value.project_id) : undefined))
</script>

<template>
  <div class="flex flex-col gap-3 px-10 py-8">
    <template v-if="session">
      <RouterLink
        v-if="project"
        :to="{ name: 'project', params: { id: project.id } }"
        class="flex w-fit items-center gap-2 text-sm text-fg-muted no-underline hover:text-fg"
      >
        <span class="size-2.5 rounded-[3px]" :style="{ backgroundColor: project.color }" />
        {{ project.name }}
      </RouterLink>
      <h1 class="m-0 text-[28px] font-semibold tracking-tight">{{ session.title }}</h1>
      <div class="flex items-center gap-2 font-mono text-xs text-fg-muted">
        <SessionStateIcon :state="session.state" />
        {{ sessionStateLabels[session.state] }}
      </div>
      <p v-if="session.error" role="alert" class="text-sm text-secondary-soft">{{ session.error }}</p>
      <p class="mt-4 rounded-lg border border-dashed border-line-strong px-5 py-8 text-center text-sm text-fg-muted">
        A conversa desta sessão aparece aqui em breve.
      </p>
    </template>
    <p v-else-if="sessions.loaded" class="text-fg-muted">
      Sessão não encontrada.
      <RouterLink to="/" class="text-primary-soft hover:underline">Voltar ao início</RouterLink>
    </p>
    <p v-else class="text-fg-muted">Carregando…</p>
  </div>
</template>
