<script setup lang="ts">
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { AGENTS_NAVIGATION_KEY } from '../agentsNavigation'
import { errorMessage } from '../api/http'
import { useWorkStore } from '../stores/work'
import { useProjectsStore } from '../stores/projects'
import { useSessionsStore } from '../stores/sessions'
import { displayStateLabel } from '../sessionState'
import { needsYou } from '../conversation/needsYou'
import { formatActivity } from '../format'
import DisplayStateIcon from '../components/DisplayStateIcon.vue'
import type { Project, Session } from '../types/api'
import type { WorkMode } from '../types/work'
import ConversationView from './ConversationView.vue'
import WorkPage from '../components/work/WorkPage.vue'
import SourcesPanel from '../components/work/SourcesPanel.vue'
const route = useRoute(), router = useRouter(), work = useWorkStore(), projects = useProjectsStore(), sessions = useSessionsStore()
const navigation = inject(AGENTS_NAVIGATION_KEY, undefined)
const projectId = computed(() => Number(route.query.projeto) || null)
const sessionId = ref<string | null>(null), mode = ref<WorkMode | null>(null), error = ref(''), loading = ref(false), busy = ref(false), sourcesOpen = ref(false)
let ticket = 0
interface CtoEntry { project: Project, session: Session | undefined }
// Projects whose CTO conversation exists and is not finished, most recent activity first; the rest are only places to start or reopen.
const listing = computed(() => {
  const open: CtoEntry[] = [], others: CtoEntry[] = []
  for (const project of projects.projects) {
    const sid = work.coordinators[project.id], session = sid ? sessions.find(sid) : undefined
    ;(sid && !session?.finished ? open : others).push({ project, session })
  }
  open.sort((a, b) => (b.session?.last_activity_at ?? 0) - (a.session?.last_activity_at ?? 0))
  return { open, others }
})
const openIds = computed(() => new Set(listing.value.open.map(entry => entry.project.id)))
async function load() {
  const mine = ++ticket, id = projectId.value
  sessionId.value = null; mode.value = null; error.value = ''; sourcesOpen.value = false; loading.value = false
  if (!id) return
  loading.value = true
  try { const [sid, projectMode] = await Promise.all([work.openCoordinator(id), work.mode(id)]); if (mine === ticket) { sessionId.value = sid; mode.value = projectMode } }
  catch (e) { if (mine === ticket) error.value = errorMessage(e) }
  finally { if (mine === ticket) loading.value = false }
}
function choose(value: string) { void router.push({ name: 'cto', query: value ? { projeto: value } : {} }) }
async function setMode(action: string) {
  if (!projectId.value || busy.value || !mode.value) return
  const id = projectId.value, mine = ticket, fence = mode.value.fence_id
  busy.value = true; error.value = ''
  try { const result = await work.setMode(id, action, action === 'cancel_delete' ? fence : undefined); if (mine === ticket) mode.value = result }
  catch (e) { if (mine === ticket) error.value = errorMessage(e) }
  finally { busy.value = false }
}
watch(projectId, () => { void load() }, { immediate: true })
watch(() => work.changeVersion, async () => { const id = projectId.value; if (!id) return; try { const value = await work.mode(id); if (projectId.value === id) mode.value = value } catch {} })
void work.runtime().catch(() => {})
onBeforeUnmount(() => ticket++)
</script>
<template>
  <div class="cto-workspace">
    <header class="cto-header">
      <button v-if="navigation?.enabled.value" class="work-menu" type="button" aria-label="Abrir navegação" :aria-expanded="navigation.open.value" @click="navigation.toggle($event.currentTarget as HTMLElement)"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" /></svg></button>
      <h1>CTO</h1><label class="cto-project"><span class="sr-only">Projeto do CTO</span><select class="work-select" :value="projectId ?? ''" @change="choose(($event.target as HTMLSelectElement).value)"><option value="">Escolher projeto</option><option v-for="project in projects.projects" :key="project.id" :value="project.id" :disabled="!project.available">{{ project.name }}{{ openIds.has(project.id) ? ' · em andamento' : '' }}</option></select></label>
      <template v-if="projectId"><RouterLink class="work-link cto-tasks" :to="`/tarefas?project=${projectId}`">Tarefas ↗</RouterLink><button class="work-button" type="button" :aria-expanded="sourcesOpen" @click="sourcesOpen = !sourcesOpen">Fontes</button></template>
    </header>
    <div v-if="mode" class="cto-mode"><span class="work-muted">{{ mode.deleting ? 'Exclusão reservada. Novos trabalhos estão bloqueados.' : !mode.enabled ? 'Coordenação ainda não ativada' : mode.paused ? 'Trabalhadores pausados' : 'Coordenação ativa' }}</span><button v-if="mode.deleting && mode.fence_id" class="work-button" :disabled="busy" @click="setMode('cancel_delete')">Cancelar reserva de exclusão</button><button v-else class="work-button" :disabled="busy" @click="setMode(!mode.enabled ? 'enable' : mode.paused ? 'resume' : 'pause')">{{ !mode.enabled ? 'Ativar coordenação' : mode.paused ? 'Retomar trabalho' : 'Pausar trabalho' }}</button><button v-if="mode.enabled && !mode.deleting" class="work-button" :disabled="busy" @click="setMode('disable')">Desativar</button></div>
    <p v-if="work.dispatcherEnabled === false && projectId" class="cto-runtime work-muted">Despacho automático desligado nesta instalação. Os trabalhadores não serão iniciados.</p>
    <p v-if="error" class="cto-error work-error" role="alert">{{ error }} <button class="work-button" type="button" @click="load">Atualizar</button></p>
    <SourcesPanel v-if="sourcesOpen && projectId" :key="projectId" :project-id="projectId" />
    <div v-if="loading" class="cto-loading work-skeleton" role="status"><span class="sr-only">Abrindo conversa do CTO…</span><span /><span /></div>
    <ConversationView v-else-if="sessionId" :key="sessionId" :id="sessionId" class="min-h-0 grow" />
    <WorkPage v-else-if="!projectId" title="Um CTO por projeto" eyebrow="Conversa contínua">
      <section v-if="listing.open.length" class="cto-section" data-test="cto-open" aria-labelledby="cto-open-title">
        <h2 id="cto-open-title">Conversas em andamento</h2>
        <div class="cto-project-list">
          <button v-for="{ project, session } in listing.open" :key="project.id" type="button" data-test="cto-item" :disabled="!project.available" @click="choose(String(project.id))">
            <span class="cto-name">{{ project.name }}</span>
            <span class="cto-meta work-muted">
              <template v-if="!project.available">Pasta indisponível</template>
              <template v-else-if="session"><DisplayStateIcon :display="session.display_state" :size="11" :quiet="!needsYou(session)" /><span>{{ displayStateLabel(session) }}</span><span aria-hidden="true">·</span><span>{{ formatActivity(session.last_activity_at) }}</span></template>
              <template v-else>Abrir conversa →</template>
            </span>
          </button>
        </div>
      </section>
      <section class="cto-section" data-test="cto-others" aria-labelledby="cto-others-title">
        <h2 v-if="listing.open.length" id="cto-others-title">Outros projetos</h2>
        <div v-else class="work-empty"><strong id="cto-others-title">Escolha onde o trabalho acontece</strong>O CTO mantém objetivos, decisões e tarefas do projeto na mesma conversa. Escolha um projeto para abrir ou começar a conversa dele.</div>
        <div class="cto-project-list">
          <button v-for="{ project } in listing.others" :key="project.id" type="button" data-test="cto-item" :disabled="!project.available" @click="choose(String(project.id))"><span class="cto-name">{{ project.name }}</span><span class="work-muted">{{ project.available ? 'Abrir conversa →' : 'Pasta indisponível' }}</span></button>
          <RouterLink v-if="!projects.projects.length" class="work-link" to="/projects/new">Cadastrar primeiro projeto →</RouterLink>
        </div>
      </section>
    </WorkPage>
  </div>
</template>
<style src="../work.css"></style>
<style scoped>
.cto-workspace{display:flex;flex-direction:column;height:100%;min-width:0;background:var(--color-surface);container-type:inline-size}.cto-header{display:flex;align-items:center;gap:14px;min-height:65px;padding:12px 24px;border-bottom:1px solid var(--color-line);flex-shrink:0}.cto-header h1{font-size:1.0625rem;font-weight:500;margin:0}.cto-project{min-width:0;flex:1}.cto-project select{max-width:280px;width:100%;font-size:0.75rem}.cto-header a{font-size:0.75rem}.cto-mode{display:flex;align-items:center;flex-wrap:wrap;gap:9px;padding:9px 24px;border-bottom:1px solid var(--color-line)}.cto-mode>span{margin-right:auto;font-size:0.6875rem}.cto-mode button{font-size:0.6875rem;min-height:28px;padding:4px 9px}.cto-runtime,.cto-error{margin:0;padding:10px 24px;border-bottom:1px solid var(--color-line);font-size:0.6875rem}.cto-loading{padding:24px}.cto-section+.cto-section{margin-top:28px}.cto-section h2{margin:0 0 6px;font-size:0.75rem;font-weight:500;color:var(--color-fg-muted)}.cto-project-list{max-width:700px}.cto-name{min-width:0;overflow-wrap:anywhere}.cto-meta{display:inline-flex;align-items:center;gap:6px;flex-shrink:0;font-size:0.75rem}.cto-project-list button{display:flex;width:100%;justify-content:space-between;align-items:center;gap:12px;text-align:left;border:0;border-top:1px solid var(--color-line);padding:18px 3px;background:transparent;color:var(--color-fg);font-size:0.8125rem;cursor:pointer}.cto-project-list button:hover{background:var(--color-panel)}.cto-project-list button:disabled{opacity:.5;cursor:default}
@container(max-width:460px){.cto-project-list button{flex-wrap:wrap;gap:4px 12px}.cto-header{gap:9px;padding:12px 14px;flex-wrap:wrap}.cto-header h1{font-size:0.9375rem}.cto-project{flex-basis:60%}.cto-header .cto-tasks{margin-left:4px}.cto-mode{padding:9px 14px}.cto-mode>span{width:100%}.cto-runtime,.cto-error{padding:9px 14px}}
</style>
