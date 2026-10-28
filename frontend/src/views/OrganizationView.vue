<script setup lang="ts">
import { computed, inject, ref, watchEffect } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import NewAgentDialog from '../components/org/NewAgentDialog.vue'
import OrgTabs from '../components/org/OrgTabs.vue'
import OrgTree from '../components/org/OrgTree.vue'
import AgentPanel from '../components/org/agent/AgentPanel.vue'
import { BTN, BTN_PRIMARY } from '../components/org/styles'
import { AGENTS_NAVIGATION_KEY } from '../agentsNavigation'
import { errorMessage } from '../api/http'
import { useOrgStore } from '../stores/org'
import { useProjectsStore } from '../stores/projects'
import { useMediaQuery } from '../useMediaQuery'
import type { Agent } from '../types/org'

const props = defineProps<{ projectId?: number }>()

// The last project looked at, so `/agentes` goes straight back to it.
const STORAGE_KEY = 'maestro.org.project'

const projects = useProjectsStore()
const org = useOrgStore()
const route = useRoute()
const router = useRouter()
const wide = useMediaQuery('(min-width: 1024px)')
const navigation = inject(AGENTS_NAVIGATION_KEY, undefined)
const compactNavigation = computed(() => navigation?.enabled.value ?? false)
const navigationOpen = computed(() => navigation?.open.value ?? false)

const project = computed(() => (props.projectId === undefined ? undefined : projects.byId(props.projectId)))
const projectsReady = computed(() => projects.loaded || projects.projects.length > 0)

function remembered(): number | null {
  try {
    const value = Number(localStorage.getItem(STORAGE_KEY))
    return Number.isInteger(value) && value > 0 ? value : null
  } catch {
    return null
  }
}

watchEffect(() => {
  if (props.projectId !== undefined) {
    if (!project.value) return
    try { localStorage.setItem(STORAGE_KEY, String(props.projectId)) } catch { /* the choice is only a convenience */ }
    return
  }
  const last = remembered()
  if (last !== null && projects.byId(last)) void router.replace({ name: 'agents', params: { projectId: last } })
})

function switchProject(event: Event): void {
  const id = Number((event.target as HTMLSelectElement).value)
  if (Number.isInteger(id)) void router.push({ name: 'agents', params: { projectId: id } })
}

const top = computed<Agent | undefined>(() => (props.projectId === undefined ? undefined : org.topOf(props.projectId)))
const selectedAgentId = computed(() => {
  const raw = route.query.agente
  const n = typeof raw === 'string' ? Number(raw) : NaN
  return Number.isInteger(n) ? n : null
})
const selectedAgent = computed(() => {
  const agent = selectedAgentId.value === null ? undefined : org.byId(selectedAgentId.value)
  return agent && agent.project_id === props.projectId ? agent : undefined
})

const creating = ref(false)
function created(agent: Agent): void {
  creating.value = false
  void router.replace({ query: { agente: String(agent.id), aba: 'definicao' } })
}

function back(): void {
  void router.replace({ query: {} })
}

const opening = ref(false)
const openError = ref<string | null>(null)
async function talkToTop(): Promise<void> {
  if (!top.value || opening.value) return
  opening.value = true
  openError.value = null
  try {
    await org.openMain(top.value.id, router)
  } catch (e) {
    openError.value = `Não foi possível abrir a conversa de ${top.value.name}. ${errorMessage(e)}`
  } finally {
    opening.value = false
  }
}
</script>

<template>
  <div class="flex h-full min-h-0 min-w-0 flex-col bg-surface">
    <!-- No project in the address: pick one -->
    <section v-if="projectId === undefined" aria-labelledby="org-pick-title" class="mx-auto flex w-full max-w-[640px] flex-col gap-4 px-6 py-10">
      <button v-if="compactNavigation" type="button" data-test="agents-mobile-menu" class="mobile-menu-button self-start" aria-label="Abrir navegação" :aria-expanded="navigationOpen" @click="navigation?.toggle($event.currentTarget as HTMLElement)">
        <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" /></svg>
      </button>
      <h1 id="org-pick-title" class="m-0 text-xl font-semibold tracking-tight">Agentes</h1>
      <p v-if="!projectsReady" role="status" class="m-0 text-fg-muted">Carregando projetos…</p>
      <p v-else-if="projects.projects.length === 0" class="m-0 text-fg-muted">Nenhum projeto ainda. <RouterLink to="/projects/new">Registre um projeto</RouterLink> para montar a organização dele.</p>
      <template v-else>
        <p class="m-0 text-fg-muted">Escolha o projeto cuja organização você quer ver.</p>
        <ul aria-labelledby="org-pick-title" class="m-0 flex list-none flex-col gap-px p-0">
          <li v-for="p in projects.projects" :key="p.id">
            <RouterLink :to="`/agentes/${p.id}`" data-test="org-project-option" class="flex items-center gap-3 rounded-lg px-3 py-2.5 text-fg no-underline hover:bg-card focus-visible:outline-2 focus-visible:outline-primary">
              <span class="size-3 shrink-0 rounded-[3px]" :style="{ backgroundColor: p.color }" aria-hidden="true" />
              <span class="truncate">{{ p.name }}</span>
            </RouterLink>
          </li>
        </ul>
      </template>
    </section>

    <p v-else-if="!project && !projectsReady" role="status" class="m-0 p-8 text-fg-muted">Carregando projetos…</p>
    <section v-else-if="!project" data-test="org-project-missing" class="mx-auto flex max-w-[640px] flex-col gap-2 px-6 py-10">
      <h1 class="m-0 text-xl font-semibold">Projeto não encontrado</h1>
      <p class="m-0 text-fg-muted">Ele pode ter sido removido. <RouterLink to="/agentes">Escolher outro projeto</RouterLink></p>
    </section>

    <template v-else>
      <header class="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-4 py-3 lg:px-6">
        <button v-if="compactNavigation" type="button" data-test="agents-mobile-menu" class="mobile-menu-button" aria-label="Abrir navegação" :aria-expanded="navigationOpen" @click="navigation?.toggle($event.currentTarget as HTMLElement)">
          <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" /></svg>
        </button>
        <div class="flex min-w-0 grow items-center gap-3">
          <span class="size-3 shrink-0 rounded-[3px]" :style="{ backgroundColor: project.color }" aria-hidden="true" />
          <h1 class="m-0 truncate text-xl font-semibold tracking-tight">{{ project.name }}</h1>
          <label v-if="projects.projects.length > 1" class="shrink-0 text-xs text-fg-subtle">
            <span class="sr-only">Trocar de projeto</span>
            <select data-test="org-project-select" class="h-8 max-w-40 rounded-md border border-line-strong bg-surface px-2 text-xs text-fg-muted focus-visible:outline-2 focus-visible:outline-primary" :value="project.id" @change="switchProject">
              <option v-for="p in projects.projects" :key="p.id" :value="p.id">{{ p.name }}</option>
            </select>
          </label>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <button v-if="top" type="button" data-test="talk-cto" :class="BTN" :disabled="opening" @click="talkToTop">Conversar com o CTO</button>
          <button type="button" data-test="new-agent" :class="BTN_PRIMARY" @click="creating = true">Novo agente</button>
        </div>
      </header>
      <p v-if="openError" role="alert" class="m-0 px-6 pt-3 text-sm text-diff-del-fg">{{ openError }}</p>
      <div v-if="org.error" data-test="org-error" role="alert" class="flex flex-wrap items-center gap-3 px-6 pt-3 text-sm text-diff-del-fg">
        <span>Não foi possível carregar os agentes. {{ org.error }}</span>
        <button type="button" :class="BTN" @click="org.load()">Tentar de novo</button>
      </div>

      <div class="flex min-h-0 min-w-0 flex-1" :class="wide ? 'flex-row' : 'flex-col overflow-y-auto'">
        <aside v-if="wide" data-test="org-tree" aria-label="Organização" class="w-[280px] shrink-0 overflow-y-auto border-r border-line p-2">
          <OrgTree :project-id="project.id" @create="creating = true" />
        </aside>
        <details v-else data-test="org-tree" open class="shrink-0 border-b border-line">
          <summary class="cursor-pointer px-4 py-2 text-sm font-medium text-fg-muted focus-visible:outline-2 focus-visible:outline-primary">Organização</summary>
          <div class="px-2 pb-2"><OrgTree :project-id="project.id" @create="creating = true" /></div>
        </details>

        <section aria-label="Área principal" class="min-w-0 flex-1 overflow-y-auto p-4 lg:px-6">
          <template v-if="selectedAgentId !== null">
            <div class="mb-3">
              <button type="button" data-test="org-back" class="cursor-pointer rounded border-0 bg-transparent p-0 text-sm text-info-soft hover:underline focus-visible:outline-2 focus-visible:outline-primary" @click="back">← Organização</button>
            </div>
            <AgentPanel v-if="selectedAgent" :key="selectedAgent.id" :agent-id="selectedAgent.id" />
            <p v-else-if="org.loaded" data-test="org-agent-missing" class="m-0 text-fg-muted"><strong class="font-semibold text-fg">Agente não encontrado.</strong> Ele pode ter sido excluído ou ser de outro projeto.</p>
            <p v-else role="status" class="m-0 text-fg-subtle">Carregando agente…</p>
          </template>
          <OrgTabs v-else :project-id="project.id" />
        </section>
      </div>
    </template>

    <NewAgentDialog v-if="creating && project" :project-id="project.id" @created="created" @cancel="creating = false" />
  </div>
</template>

<style scoped>
.mobile-menu-button { display:flex; width:32px; height:36px; flex-shrink:0; align-items:center; justify-content:center; cursor:pointer; border:0; border-radius:6px; background:transparent; color:var(--color-fg-muted); }
.mobile-menu-button:hover { background:var(--color-card); color:var(--color-fg); }
.mobile-menu-button:focus-visible { outline:2px solid var(--color-primary); outline-offset:3px; }
</style>
