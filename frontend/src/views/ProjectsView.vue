<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { RouterLink } from 'vue-router'
import OrgPage from '../components/org/OrgPage.vue'
import { errorMessage } from '../api/http'
import { isDiscarded } from '../conversation/marks'
import { useSessionsStore } from '../stores/sessions'
import { useProjectsStore } from '../stores/projects'
import type { Project } from '../types/api'

const projects = useProjectsStore()
const sessions = useSessionsStore()
const query = ref('')
const searchInput = ref<HTMLInputElement | null>(null)
const actions = ref<number | null>(null)
const visibleProjects = computed(() => {
  const term = query.value.trim().toLocaleLowerCase('pt-BR')
  return projects.regular.filter(p => `${p.name} ${p.path}`.toLocaleLowerCase('pt-BR').includes(term))
})
const activity = computed(() => Object.fromEntries(projects.regular.map(project => {
  const list = sessions.forProject(project.id).filter(session => !isDiscarded(session))
  const running = list.filter(s => s.display_state === 'running').length
  const open = list.filter(s => s.display_state !== 'finished').length
  const latest = Math.max(0, ...list.map(s => s.last_activity_at))
  return [project.id, { running, open, latest }]
})))
function activityDate(timestamp: number) {
  return new Date(timestamp * 1000).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
}
function closeActions(event: FocusEvent) {
  if (!(event.currentTarget as HTMLElement).contains(event.relatedTarget as Node | null)) actions.value = null
}
const editing = ref<number | null>(null)
const name = ref('')
const saving = ref(false)
const retrying = ref(false)
const error = ref('')
const notice = ref('')
const input = ref<HTMLInputElement[]>([])
let renameTrigger: HTMLElement | null = null

async function startRename(project: Project, trigger: HTMLElement) {
  if (saving.value) return
  renameTrigger = trigger.closest('[data-test="project-row"]')?.querySelector<HTMLElement>('[data-test="project-actions"]') ?? trigger
  actions.value = null
  editing.value = project.id
  name.value = project.name
  error.value = ''
  notice.value = ''
  await nextTick()
  input.value[0]?.focus()
  input.value[0]?.select()
}

async function cancelRename() {
  if (saving.value) return
  editing.value = null
  error.value = ''
  await nextTick()
  if (renameTrigger?.isConnected) renameTrigger.focus()
  else searchInput.value?.focus()
}

async function saveRename() {
  if (saving.value || editing.value === null) return
  const trimmed = name.value.trim()
  if (!trimmed) {
    error.value = 'O nome não pode ficar vazio.'
    return
  }
  if (trimmed.length > 100) {
    error.value = 'Use até 100 caracteres no nome.'
    return
  }
  saving.value = true
  error.value = ''
  try {
    await projects.rename(editing.value, trimmed)
    notice.value = 'Nome do projeto atualizado.'
    saving.value = false
    await cancelRename()
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    saving.value = false
  }
}

async function retry() {
  if (retrying.value) return
  retrying.value = true
  try { await projects.load() }
  catch { /* The shared store displays the load error. */ }
  finally { retrying.value = false }
}
</script>

<template>
  <OrgPage title="Projetos">
    <template #actions>
      <RouterLink to="/projects/new" class="org-button org-primary">Novo projeto</RouterLink>
    </template>

    <p v-if="notice" role="status" class="mb-4 text-sm text-primary">{{ notice }}</p>
    <p v-if="projects.loadError" role="alert" class="org-error mb-4">
      Não foi possível carregar os projetos. {{ projects.loadError }}
      <button type="button" data-test="retry-projects" class="org-button ml-2" :disabled="retrying" @click="retry">{{ retrying ? 'Carregando…' : 'Tentar novamente' }}</button>
    </p>
    <div v-if="!projects.loaded && !projects.regular.length" class="org-skeleton" role="status">
      <span class="sr-only">Carregando projetos…</span><span /><span /><span />
    </div>
    <div v-else-if="projects.loaded && !projects.regular.length && !projects.loadError" class="org-empty">
      <strong>Nenhum projeto cadastrado</strong>
      Adicione uma pasta em Novo projeto para começar.
    </div>
    <template v-if="projects.regular.length">
      <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
        <label class="org-field min-w-0 grow sm:max-w-sm">
          <span class="sr-only">Buscar projetos por nome ou caminho</span>
          <input ref="searchInput" v-model="query" data-test="project-search" type="search" placeholder="Buscar por nome ou caminho" autocomplete="off" />
        </label>
        <p class="org-muted m-0">{{ projects.regular.length }} {{ projects.regular.length === 1 ? 'projeto cadastrado' : 'projetos cadastrados' }}</p>
      </div>
      <p v-if="!visibleProjects.length" role="status" class="org-empty">Nenhum projeto encontrado. Tente outro nome ou caminho.</p>
      <ul class="m-0 list-none p-0" aria-label="Projetos cadastrados">
        <li v-for="project in visibleProjects" :key="project.id" data-test="project-row" class="flex flex-wrap items-start gap-x-4 gap-y-3 border-t border-line py-4">
          <span aria-hidden="true" class="mt-1.5 size-2.5 shrink-0 rounded-sm" :style="{ backgroundColor: project.color }" />
          <div class="min-w-0 flex-1 basis-44">
            <RouterLink :to="{ name: 'project', params: { id: project.id } }" class="font-medium break-words text-fg no-underline hover:underline focus-visible:outline-2 focus-visible:outline-primary">{{ project.name }}</RouterLink>
            <p data-test="project-path" class="mt-1 font-mono text-xs break-all text-fg-subtle">{{ project.path }}</p>
            <p v-if="activity[project.id]?.open || activity[project.id]?.latest" data-test="project-activity" class="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-fg-muted">
              <span v-if="activity[project.id]?.running" class="text-primary">{{ activity[project.id]?.running }} em execução</span>
              <span v-if="activity[project.id]?.open">{{ activity[project.id]?.open }} {{ activity[project.id]?.open === 1 ? 'conversa aberta' : 'conversas abertas' }}</span>
              <span v-if="activity[project.id]?.latest">Última atividade: {{ activityDate(activity[project.id]!.latest) }}</span>
            </p>
            <p v-if="!project.available" class="mt-1 text-xs text-secondary-soft">Pasta indisponível</p>
            <form v-if="editing === project.id" class="mt-4 flex flex-wrap items-end gap-2" :aria-label="`Renomear ${project.name}`" @submit.prevent="saveRename" @keydown.esc.prevent="cancelRename">
              <label class="org-field grow" :for="`project-name-${project.id}`">Nome do projeto
                <input :id="`project-name-${project.id}`" ref="input" v-model="name" type="text" maxlength="100" autocomplete="off" :disabled="saving" :aria-invalid="error ? true : undefined" :aria-describedby="error ? 'project-rename-error' : undefined" />
              </label>
              <button type="submit" class="org-button org-primary" :disabled="saving">{{ saving ? 'Salvando…' : 'Salvar' }}</button>
              <button type="button" class="org-button" :disabled="saving" @click="cancelRename">Cancelar</button>
              <p v-if="error" id="project-rename-error" role="alert" class="org-error w-full">{{ error }}</p>
            </form>
          </div>
          <div class="relative shrink-0" @focusout="closeActions" @keydown.esc.stop.prevent="actions = null; ($event.currentTarget as HTMLElement).querySelector<HTMLButtonElement>('button')?.focus()">
            <button type="button" data-test="project-actions" class="org-button" :aria-label="`Ações de ${project.name}`" :aria-expanded="actions === project.id" :aria-controls="`project-actions-${project.id}`" :disabled="saving || editing === project.id" @click="actions = actions === project.id ? null : project.id"><span aria-hidden="true">•••</span></button>
            <div v-if="actions === project.id" :id="`project-actions-${project.id}`" class="absolute right-0 top-full z-10 mt-1 min-w-40 rounded-md border border-line-strong bg-panel p-1 shadow-lg">
              <button type="button" data-test="rename-project" class="org-button w-full text-left" :aria-label="`Renomear ${project.name}`" @click="startRename(project, $event.currentTarget as HTMLElement)">Renomear</button>
            </div>
          </div>
        </li>
      </ul>
    </template>
  </OrgPage>
</template>
