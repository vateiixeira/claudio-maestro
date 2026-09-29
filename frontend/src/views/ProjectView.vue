<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import SessionStateIcon from '../components/SessionStateIcon.vue'
import SessionGroup from '../components/session/SessionGroup.vue'
import { errorMessage } from '../api/http'
import { displayStateLabels } from '../sessionState'
import type { DisplayState } from '../types/api'
import { useProjectsStore } from '../stores/projects'
import { useSessionsStore } from '../stores/sessions'

const props = defineProps<{ id: number }>()

const projects = useProjectsStore()
const sessions = useSessionsStore()
const router = useRouter()

const project = computed(() => projects.byId(props.id))
const projectSessions = computed(() => sessions.forProject(props.id))

const groups = computed(() =>
  (['running', 'waiting', 'finished'] as DisplayState[]).map((display) => ({
    display,
    title: display === 'finished' ? 'Finalizadas' : displayStateLabels[display],
    sessions: projectSessions.value.filter((s) => s.display_state === display),
  })),
)

const sessionsError = ref<string | null>(null)
const actionError = ref<string | null>(null)
const creating = ref(false)

const renaming = ref(false)
const renameValue = ref('')
const renameError = ref<string | null>(null)
const renameInput = ref<HTMLInputElement | null>(null)

const confirmingRemove = ref(false)
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
  try {
    await sessions.loadForProject(props.id)
  } catch (e) {
    sessionsError.value = errorMessage(e)
  }
}

watch(() => props.id, load, { immediate: true })

async function newSession(): Promise<void> {
  if (!project.value?.available || creating.value) return
  creating.value = true
  actionError.value = null
  try {
    const session = await sessions.create(props.id)
    await router.push({ name: 'session', params: { id: session.session_id } })
  } catch (e) {
    actionError.value = errorMessage(e)
  } finally {
    creating.value = false
  }
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
    await router.push('/')
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
      <RouterLink to="/" class="text-primary-soft hover:underline">Voltar ao início</RouterLink>
    </p>
    <p v-else class="text-fg-muted">Carregando…</p>
  </div>

  <div v-else class="flex max-w-5xl flex-col gap-6 px-10 py-8">
    <header class="flex flex-wrap items-start gap-4">
      <div class="flex min-w-0 flex-1 flex-col gap-1.5">
        <form
          v-if="renaming"
          data-test="rename-form"
          class="flex flex-wrap items-center gap-2"
          @submit.prevent="saveRename"
          @keydown.esc="renaming = false"
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
          data-test="rename"
          class="h-11 rounded-lg border border-line-strong px-4 font-medium text-fg hover:bg-card"
          @click="startRename"
        >
          Renomear
        </button>
        <button
          type="button"
          data-test="remove"
          class="h-11 rounded-lg border border-line-strong px-4 font-medium text-fg hover:bg-card"
          @click="confirmingRemove = true; renaming = false"
        >
          Remover
        </button>
        <button
          type="button"
          data-test="new-session"
          class="flex h-11 items-center gap-2 rounded-lg bg-primary px-4 font-semibold text-primary-fg hover:bg-primary-soft disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-primary"
          :disabled="!project.available || creating"
          :aria-describedby="project.available ? undefined : 'new-session-hint'"
          @click="newSession"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          {{ creating ? 'Abrindo…' : 'Nova sessão' }}
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

    <section
      v-if="confirmingRemove"
      data-test="confirm-remove"
      role="alertdialog"
      aria-labelledby="confirm-remove-title"
      aria-describedby="confirm-remove-text"
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
          data-test="confirm-remove-cancel"
          class="h-11 rounded-lg border border-line-strong px-4 font-medium text-fg hover:bg-panel"
          @click="confirmingRemove = false"
        >
          Cancelar
        </button>
      </div>
    </section>

    <p v-if="sessionsError" role="alert" class="text-sm text-secondary-soft">{{ sessionsError }}</p>
    <p v-else-if="projectSessions.length === 0" class="text-sm text-fg-muted">
      Nenhuma sessão ainda. Use "Nova sessão" para começar uma conversa nesta pasta.
    </p>
    <template v-else>
      <template v-for="group in groups" :key="group.display">
        <SessionGroup
          v-if="group.sessions.length > 0"
          :data-test="`block-${group.display}`"
          :display="group.display"
          :title="group.title"
          :sessions="group.sessions"
          @error="actionError = $event"
        />
      </template>
    </template>
  </div>
</template>
