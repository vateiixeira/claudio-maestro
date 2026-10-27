<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { errorMessage, sendMessage } from '../api/http'
import { useWorkStore } from '../stores/work'
import { useProjectsStore } from '../stores/projects'
import { useSessionsStore } from '../stores/sessions'
import { needsYou } from '../conversation/needsYou'
import { isDiscarded } from '../conversation/marks'
import { goalDrafts } from '../workGoal'
import type { WorkItem, WorkDecision, WorkNotice } from '../types/work'
import WorkPage from '../components/work/WorkPage.vue'
import TaskRow from '../components/work/TaskRow.vue'
import DecisionRequest from '../components/work/DecisionRequest.vue'
const work = useWorkStore(), projects = useProjectsStore(), router = useRouter(), route = useRoute()
const selected = ref(typeof route.query.projeto === 'string' ? route.query.projeto : '')
const goal = computed({ get: () => goalDrafts[selected.value] ?? '', set: (value: string) => { goalDrafts[selected.value] = value } })
watch(selected, (value, before) => { void router.replace({ query: { ...route.query, projeto: value || undefined } }); if (!before && value && goalDrafts[''] && !goalDrafts[value]) { goalDrafts[value] = goalDrafts['']; delete goalDrafts[''] } })
const busy = ref(false), error = ref(''), loading = ref(true), loadError = ref(''), items = ref<WorkItem[]>([]), decisions = ref<WorkDecision[]>([]), notices = ref<WorkNotice[]>([])
const nativePending = computed(() => useSessionsStore().all.filter(session => session.display_state === 'waiting' && needsYou(session) && !isDiscarded(session)))
const active = computed(() => items.value.filter(item => ['active', 'waiting', 'review', 'blocked', 'ready'].includes(item.status)).slice(0, 8))
const recent = computed(() => items.value.filter(item => item.status === 'done').slice(0, 5))
let ticket = 0, alive = true
async function load() {
  const mine = ++ticket; loadError.value = ''; loading.value = true
  const results = await Promise.allSettled([Promise.all(['active', 'waiting', 'review', 'blocked', 'ready', 'done'].map(status => work.list({ status, limit: status === 'done' ? 5 : 8, offset: 0 }))), work.decisions(), work.feed(), work.runtime()])
  if (mine !== ticket) return
  if (results[0].status === 'fulfilled') items.value = results[0].value.flatMap(page => page.items).sort((a, b) => b.updated_at - a.updated_at || b.id - a.id)
  if (results[1].status === 'fulfilled') decisions.value = results[1].value.items
  if (results[2].status === 'fulfilled') notices.value = results[2].value.items
  const failed = results.find(result => result.status === 'rejected')
  if (failed?.status === 'rejected') loadError.value = errorMessage(failed.reason)
  loading.value = false
}
async function submit() {
  const projectKey = selected.value, projectId = Number(projectKey), text = goal.value.trim()
  if (!projectId || !text || busy.value) return
  busy.value = true; error.value = ''
  try { const sid = await work.openCoordinator(projectId); await sendMessage(sid, text); goalDrafts[projectKey] = ''; if (alive) await router.push({ name: 'cto', query: { projeto: projectId } }) }
  catch (e) { error.value = errorMessage(e) + ' O objetivo foi preservado. Confira a conversa antes de repetir o envio.' }
  finally { busy.value = false }
}
watch(() => work.changeVersion, () => { void load() })
void load()
onBeforeUnmount(() => { ticket++; alive = false })
</script>
<template>
  <WorkPage title="O que vamos resolver?" eyebrow="Cláudio Maestro">
    <template #actions><RouterLink class="work-button" to="/tarefas">Ver tarefas →</RouterLink></template>
    <form class="goal-form" @submit.prevent="submit">
      <label class="work-field goal-label"><span class="sr-only">Objetivo para o CTO</span><textarea v-model="goal" :disabled="busy" maxlength="6000" placeholder="Descreva um objetivo. O CTO organiza as tarefas e acompanha cada entrega." /></label>
      <div class="goal-footer"><label class="goal-project">Projeto<select v-model="selected" class="work-select" :disabled="busy" aria-label="Projeto do objetivo"><option value="">Escolher projeto</option><option v-for="project in projects.projects" :key="project.id" :value="String(project.id)" :disabled="!project.available">{{ project.name }}{{ !project.available ? ' (indisponível)' : '' }}</option></select></label><button data-test="goal-submit" class="work-button work-primary" :disabled="busy || !selected || !goal.trim()" type="submit">{{ busy ? 'Entregando…' : 'Entregar ao CTO' }} <span aria-hidden="true">↗</span></button></div>
      <p v-if="error" class="work-error" role="alert">{{ error }}</p>
    </form>
    <p v-if="work.dispatcherEnabled === false" class="work-note">O despacho automático está desligado nesta instalação. Você pode conversar com o CTO e consultar as tarefas; os trabalhadores não serão iniciados.</p>
    <p v-if="loadError" class="work-error" role="alert">Não foi possível atualizar toda a visão geral. {{ loadError }} <button class="work-button" type="button" @click="load">Tentar novamente</button></p>
    <div v-if="loading && !items.length" role="status" class="work-skeleton"><span class="sr-only">Carregando trabalho…</span><span /><span /><span /></div>
    <template v-else>
      <section v-if="nativePending.length" class="work-section" aria-labelledby="native-pending-title"><div class="work-section-header"><h2 id="native-pending-title">Permissões e perguntas nas conversas</h2></div><RouterLink v-for="session in nativePending" :key="session.session_id" class="work-row" :to="`/sessions/${session.session_id}`"><span>{{ session.title || 'Conversa sem título' }}<span class="work-row-meta">{{ projects.byId(session.project_id)?.name }}</span></span><span class="work-status" data-status="waiting">△ Responder ao pedido</span></RouterLink></section>
      <section v-if="decisions.length" class="work-section" aria-labelledby="decisions-title"><div class="work-section-header"><h2 id="decisions-title">Precisam de você <span class="work-muted">{{ decisions.length }}</span></h2></div><DecisionRequest v-for="decision in decisions" :key="decision.id" :decision="decision" @answered="load" @stale="load" /></section>
      <div class="start-columns">
        <section class="work-section" aria-labelledby="active-title"><div class="work-section-header"><h2 id="active-title">Em andamento</h2><RouterLink class="work-link" to="/tarefas?status=active">Ver todas</RouterLink></div><TaskRow v-for="item in active" :key="item.id" :item="item" /><div v-if="!active.length && !loadError" class="work-empty"><strong>O próximo passo começa com um objetivo</strong>Escolha o projeto acima e conte ao CTO o que precisa resolver.</div></section>
        <section class="work-section" aria-labelledby="recent-title"><div class="work-section-header"><h2 id="recent-title">Entregas recentes</h2></div><TaskRow v-for="item in recent" :key="item.id" :item="item" /><div v-if="!recent.length && !loadError" class="work-empty">As entregas aparecem aqui depois da conclusão da tarefa e da validação das evidências.</div><ul v-if="notices.length" class="recent-notices"><li v-for="notice in notices.slice(-5).reverse()" :key="notice.id"><RouterLink class="work-link" :to="`/tarefas/${notice.work_item_id}`">{{ notice.summary }}</RouterLink><span class="work-muted">{{ projects.byId(notice.project_id)?.name }}</span></li></ul></section>
      </div>
    </template>
  </WorkPage>
</template>
<style scoped>
.goal-form{max-width:900px;border:1px solid var(--color-line-strong);border-radius:9px;padding:18px 18px 14px;margin:4px 0 24px;background:var(--color-panel)}.goal-label textarea{border:0;background:transparent;padding:0;min-height:90px;resize:vertical;font-size:0.875rem;line-height:1.8}.goal-label textarea:focus-visible{outline-offset:7px}.goal-footer{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-top:15px}.goal-project{display:flex;gap:10px;align-items:center;font-size:0.6875rem;color:var(--color-fg-subtle);min-width:0}.goal-project select{max-width:240px;font-size:0.75rem;background:var(--color-surface);padding:7px 9px}.start-columns{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,.8fr);gap:40px}.start-columns :deep(.work-row){grid-template-columns:minmax(0,1fr) 110px}.start-columns :deep(.work-row-project){display:none}.recent-notices{list-style:none;padding:0;margin:18px 0}.recent-notices li{display:flex;flex-direction:column;gap:6px;font-size:0.75rem;line-height:1.7;border-top:1px solid var(--color-line);padding:12px 0}
@container(max-width:900px){.start-columns{grid-template-columns:1fr;gap:0}}@container(max-width:460px){.goal-form{padding:16px 13px}.goal-footer{align-items:stretch;flex-direction:column}.goal-project{justify-content:space-between}.goal-project select{max-width:76%;width:76%}.start-columns :deep(.work-row){grid-template-columns:1fr}.goal-footer button{align-self:flex-end}}
</style>
