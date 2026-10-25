<script setup lang="ts">
import { computed, inject, onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import AgentDetail from '../components/agents/AgentDetail.vue'
import AgentList from '../components/agents/AgentList.vue'
import AgentsGithub from '../components/agents/AgentsGithub.vue'
import NewAgentDialog from '../components/agents/NewAgentDialog.vue'
import IconAgents from '../components/icons/IconAgents.vue'
import IconChevron from '../components/icons/IconChevron.vue'
import { AGENTS_NAVIGATION_KEY } from '../agentsNavigation'
import { useSpecialistsStore } from '../stores/specialists'
import type { Specialist } from '../types/api'

const props = defineProps<{ id?: string }>()
const store = useSpecialistsStore()
const router = useRouter()
const route = useRoute()
const navigation = inject(AGENTS_NAVIGATION_KEY, undefined)
const compactNavigation = computed(() => navigation?.enabled.value ?? false)
const navigationOpen = computed(() => navigation?.open.value ?? false)
const githubOpen = computed(() => route.query.github === '1')
function openGithub() { void router.push({ name: 'agents', query: { github: '1' } }) }
const selectedId = computed(() => {
  const n = Number(props.id)
  return props.id !== undefined && Number.isInteger(n) ? n : null
})
const selected = computed(() => selectedId.value === null ? undefined : store.byId(selectedId.value))
const creating = ref(false)
function created(agent: Specialist) {
  creating.value = false
  void router.push({ name: 'agents', params: { id: agent.id } })
}
onMounted(() => { void store.load() })
</script>

<template>
  <div class="agents-workspace @container">
    <div class="agents-directory-wrap">
      <div class="agents-directory-inner">
        <button v-if="compactNavigation" type="button" data-test="agents-mobile-menu" class="mobile-menu-button" aria-label="Abrir navegação" :aria-expanded="navigationOpen" @click="navigation?.toggle($event.currentTarget as HTMLElement)">
          <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" /></svg>
        </button>
        <AgentList class="grow" :agents="store.list" :selected-id="selectedId" :loading="!store.loaded" @new="creating = true" @github="openGithub" />
      </div>
    </div>
    <section aria-label="Detalhe do agente" class="agents-workspace-content">
      <div class="agents-content-inner">
        <p v-if="store.error" role="alert" class="workspace-error">Não foi possível carregar os agentes. {{ store.error }}</p>
        <div v-if="githubOpen" class="github-page"><AgentsGithub /></div>
        <AgentDetail v-else-if="selected" :key="selected.id" :agent="selected" />
        <div v-else-if="selectedId !== null && store.loaded && !store.error" data-test="agent-missing" class="workspace-empty">
          <IconAgents :size="30" class="text-fg-subtle" />
          <h2>Agente não encontrado</h2>
          <p>Ele pode ter sido excluído. <RouterLink :to="{ name: 'agents' }">Voltar aos agentes</RouterLink></p>
        </div>
        <div v-else-if="selectedId === null && store.loaded" class="agents-overview">
          <div data-test="agent-empty-detail" class="overview-heading"><p class="overview-eyebrow">Suas rotinas, com contexto</p><h2>Um agente para cada trabalho.</h2><p>Escolha um agente para conversar, acompanhar as execuções ou ajustar como ele trabalha.</p></div>
          <ul v-if="store.list.length" class="overview-agents">
            <li v-for="agent in store.list" :key="agent.id"><RouterLink :to="{ name: 'agents', params: { id: agent.id } }" data-test="agent-overview-item"><span class="overview-avatar"><IconAgents :size="19" /></span><span class="min-w-0 grow"><span class="block font-medium">{{ agent.name }}</span><span class="block truncate text-xs text-fg-subtle">{{ agent.description || 'Configurar uma rotina e começar a conversar' }}</span></span><IconChevron :size="15" class="-rotate-90 text-fg-subtle" /></RouterLink></li>
          </ul>
          <div class="overview-github"><AgentsGithub /></div>
        </div>
        <div v-else-if="!store.loaded" role="status" class="workspace-loading"><span class="sr-only">Carregando agentes…</span><span /><span /><span /></div>
      </div>
    </section>
    <NewAgentDialog v-if="creating" @created="created" @cancel="creating = false" />
  </div>
</template>

<style scoped>
.agents-workspace { display:grid; height:100%; min-height:0; min-width:0; grid-template-rows:auto minmax(0,1fr); background:var(--color-surface); }
.agents-directory-wrap { min-width:0; border-bottom:1px solid var(--color-line); }
.agents-directory-inner { display:flex; width:100%; max-width:1248px; align-items:center; gap:10px; margin:auto; padding:0 32px; }
.agents-workspace-content { min-height:0; min-width:0; overflow:auto; scroll-behavior:smooth; scrollbar-gutter:stable; }
.agents-content-inner { container-type:inline-size; width:100%; max-width:1248px; margin:0 auto; padding:0 32px; }
.mobile-menu-button { display:flex; width:32px; height:36px; flex-shrink:0; align-items:center; justify-content:center; cursor:pointer; border:0; border-radius:6px; background:transparent; color:var(--color-fg-muted); }
.mobile-menu-button:hover { background:var(--color-card); color:var(--color-fg); }
.mobile-menu-button:focus-visible { outline:2px solid var(--color-primary); outline-offset:3px; }
.workspace-error { margin:20px 0; color:var(--color-diff-del-fg); font-size:13px; }
.github-page { max-width:780px; padding:36px 0; }
.workspace-empty { display:flex; align-items:flex-start; flex-direction:column; gap:14px; padding:80px 0; }
.workspace-empty h2 { margin:0; font-size:22px; font-weight:500; }
.workspace-empty p { margin:0; color:var(--color-fg-muted); font-size:13px; }
.workspace-empty a { color:var(--color-info-soft); }
.agents-overview { padding:44px 0 60px; }
.overview-eyebrow { margin:0 0 12px; font-size:12px; color:var(--color-fg-subtle); }
.overview-heading h2 { margin:0; font-size:30px; font-weight:500; line-height:1.3; letter-spacing:-.035em; }
.overview-heading>p:last-child { max-width:60ch; margin:14px 0 0; font-size:13px; line-height:1.7; color:var(--color-fg-muted); }
.overview-agents { margin:36px 0 0; padding:0; list-style:none; }
.overview-agents a { display:flex; min-height:80px; align-items:center; gap:16px; border-top:1px solid var(--color-line); padding:16px 8px; color:var(--color-fg); text-decoration:none; }
.overview-agents a:hover { background:var(--color-panel); }
.overview-agents a:focus-visible { outline:2px solid var(--color-primary); }
.overview-avatar { display:flex; width:40px; height:40px; flex-shrink:0; align-items:center; justify-content:center; border:1px solid var(--color-line); border-radius:11px; background:var(--color-panel); color:var(--color-fg-muted); }
.overview-github { max-width:780px; margin-top:44px; border-top:1px solid var(--color-line); padding-top:28px; }
.workspace-loading { display:flex; flex-direction:column; gap:18px; padding-top:36px; }
.workspace-loading>span:not(.sr-only) { display:block; height:18px; max-width:65%; border-radius:5px; background:var(--color-panel); }
.workspace-loading>span:nth-child(2) { height:34px; max-width:40%; }
@container (max-width:620px) { .agents-directory-inner,.agents-content-inner { padding-right:20px; padding-left:20px; } .overview-heading h2 { font-size:26px; } }
@container (max-width:420px) { .agents-directory-inner,.agents-content-inner { padding-right:16px; padding-left:16px; } .agents-directory-inner { gap:4px; } }
@media (prefers-reduced-motion:reduce) { .agents-workspace-content { scroll-behavior:auto; } }
</style>
