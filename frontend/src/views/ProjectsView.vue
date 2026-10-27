<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { RouterLink } from 'vue-router'
import WorkPage from '../components/work/WorkPage.vue'
import { errorMessage } from '../api/http'
import { useProjectsStore } from '../stores/projects'
import type { Project } from '../types/api'

const projects = useProjectsStore()
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
  renameTrigger = trigger
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
  <WorkPage title="Projetos">
    <template #actions>
      <RouterLink to="/projects/new" class="work-button work-primary">Novo projeto</RouterLink>
    </template>
    <p class="mb-6 max-w-prose text-sm text-fg-muted">Gerencie os nomes cadastrados no Maestro. Renomear um projeto mantém o nome e o caminho da pasta.</p>
    <p v-if="notice" role="status" class="mb-4 text-sm text-primary">{{ notice }}</p>
    <p v-if="projects.loadError" role="alert" class="work-error mb-4">
      Não foi possível carregar os projetos. {{ projects.loadError }}
      <button type="button" data-test="retry-projects" class="work-button ml-2" :disabled="retrying" @click="retry">{{ retrying ? 'Carregando…' : 'Tentar novamente' }}</button>
    </p>
    <div v-if="!projects.loaded && !projects.projects.length" class="work-skeleton" role="status">
      <span class="sr-only">Carregando projetos…</span><span /><span /><span />
    </div>
    <div v-else-if="projects.loaded && !projects.projects.length && !projects.loadError" class="work-empty">
      <strong>Nenhum projeto cadastrado</strong>
      Adicione uma pasta em Novo projeto para começar.
    </div>
    <template v-if="projects.projects.length">
      <p class="work-muted mb-3">{{ projects.projects.length }} {{ projects.projects.length === 1 ? 'projeto cadastrado' : 'projetos cadastrados' }}</p>
      <ul class="m-0 list-none p-0" aria-label="Projetos cadastrados">
        <li v-for="project in projects.projects" :key="project.id" data-test="project-row" class="flex flex-wrap items-start gap-x-4 gap-y-3 border-t border-line py-5">
          <span aria-hidden="true" class="mt-1.5 size-2.5 shrink-0 rounded-sm" :style="{ backgroundColor: project.color }" />
          <div class="min-w-0 flex-1 basis-44">
            <RouterLink :to="{ name: 'project', params: { id: project.id } }" class="font-medium break-words text-fg no-underline hover:underline focus-visible:outline-2 focus-visible:outline-primary">{{ project.name }}</RouterLink>
            <p data-test="project-path" class="mt-1 font-mono text-xs break-all text-fg-subtle">{{ project.path }}</p>
            <p v-if="!project.available" class="mt-1 text-xs text-secondary-soft">Pasta indisponível</p>
            <form v-if="editing === project.id" class="mt-4 flex flex-wrap items-end gap-2" :aria-label="`Renomear ${project.name}`" @submit.prevent="saveRename" @keydown.esc.prevent="cancelRename">
              <label class="work-field grow" :for="`project-name-${project.id}`">Nome do projeto
                <input :id="`project-name-${project.id}`" ref="input" v-model="name" type="text" maxlength="100" autocomplete="off" :disabled="saving" :aria-invalid="error ? true : undefined" :aria-describedby="error ? 'project-rename-error' : undefined" />
              </label>
              <button type="submit" class="work-button work-primary" :disabled="saving">{{ saving ? 'Salvando…' : 'Salvar' }}</button>
              <button type="button" class="work-button" :disabled="saving" @click="cancelRename">Cancelar</button>
              <p v-if="error" id="project-rename-error" role="alert" class="work-error w-full">{{ error }}</p>
            </form>
          </div>
          <button type="button" data-test="rename-project" class="work-button" :aria-label="`Renomear ${project.name}`" :disabled="saving || editing === project.id" @click="startRename(project, $event.currentTarget as HTMLElement)">Renomear</button>
        </li>
      </ul>
    </template>
  </WorkPage>
</template>
