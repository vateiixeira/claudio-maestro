<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { ApiError, errorMessage, request } from '../api/http'
import { useWorkStore } from '../stores/work'
import { useProjectsStore } from '../stores/projects'
import { label } from '../types/work'
import WorkPage from '../components/work/WorkPage.vue'
import WorkStatus from '../components/work/WorkStatus.vue'
import AttemptResult from '../components/work/AttemptResult.vue'
import DecisionRequest from '../components/work/DecisionRequest.vue'
import TaskActivity from '../components/work/TaskActivity.vue'
import ReviewRecord from '../components/work/ReviewRecord.vue'
import TaskPullRequests from '../components/work/TaskPullRequests.vue'
const props = defineProps<{ id: string }>()
const work = useWorkStore(), projects = useProjectsStore()
const detail = computed(() => work.details[Number(props.id)])
const loading = ref(true), error = ref(''), busy = ref(false), mutationError = ref('')
const nextStep = computed(() => { const value = detail.value; if (!value) return ''; const last = value.attempts.at(-1); return String(last?.result?.next_action ?? ({ backlog: 'Iniciar a tarefa quando estiver pronta.', ready: 'Aguardando um trabalhador disponível.', active: 'Trabalhador em execução. Acompanhe a tentativa abaixo.', waiting: 'Responder ao pedido de continuidade desta tarefa.', blocked: 'Conferir o bloqueio antes de reavaliar.', review: 'Aguardando a revisão independente.', done: 'Entrega concluída e registrada.', cancelled: 'Trabalho cancelado.' }[value.item.status])) })
const eligible = computed(() => detail.value && ['backlog', 'ready', 'blocked'].includes(detail.value.item.status))
let ticket = 0
async function load() {
  const mine = ++ticket; loading.value = true; error.value = ''
  try { await work.loadDetail(Number(props.id)) } catch (e) { if (mine === ticket) error.value = errorMessage(e) }
  finally { if (mine === ticket) loading.value = false }
}
async function start() {
  if (!detail.value || busy.value) return
  busy.value = true; mutationError.value = ''
  try { await request('POST', `/api/work-items/${props.id}/start`, { expected_revision: detail.value.item.revision }); await load() }
  catch (e) { mutationError.value = errorMessage(e); if (e instanceof ApiError && e.status === 409) await load() }
  finally { busy.value = false }
}
const when = (timestamp: number) => new Date(timestamp * 1000).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })

void work.runtime().catch(() => {})
watch(() => [props.id, work.changeVersion], () => { void load() }, { immediate: true })
onBeforeUnmount(() => ticket++)
</script>
<template>
  <WorkPage :title="detail?.item.title ?? 'Tarefa'" :eyebrow="`Tarefa #${id}`">
    <template #actions><RouterLink class="work-button" to="/tarefas">← Tarefas</RouterLink></template>
    <p v-if="error" role="alert" class="work-error">{{ error }} <button class="work-button" type="button" @click="load">Tentar novamente</button></p>
    <div v-if="loading && !detail" class="work-skeleton" role="status"><span class="sr-only">Carregando tarefa…</span><span /><span /><span /></div>
    <template v-if="detail">
      <div class="task-top"><WorkStatus :status="detail.item.status" /><button v-if="eligible" class="work-button work-primary" :disabled="busy" @click="start">{{ busy ? 'Registrando…' : detail.attempts.length ? 'Reavaliar tarefa' : 'Iniciar tarefa' }}</button><RouterLink class="work-link" :to="`/cto?projeto=${detail.item.project_id}`">Conversar com CTO ↗</RouterLink></div>
      <p v-if="nextStep" class="work-note"><span class="block text-fg text-xs mb-1">Próximo passo</span>{{ nextStep }}</p>
      <p v-if="mutationError" class="work-error" role="alert">{{ mutationError }}</p>
      <p v-if="work.dispatcherEnabled === false" class="work-note">Despacho automático desligado. A tarefa permanece registrada e não iniciará um trabalhador agora.</p>
      <div class="work-detail-grid"><div class="min-w-0">
        <p v-if="detail.dossier?.unavailable" role="alert" class="work-error">{{ detail.dossier.reason }} Não é possível conferir o objetivo e os critérios desta tarefa.</p>
        <section class="work-section"><div class="work-section-header"><h2>Objetivo</h2></div><p class="work-prose">{{ detail.dossier?.objective || 'Objetivo não disponível.' }}</p></section>
        <section v-if="detail.dossier?.acceptance" class="work-section"><div class="work-section-header"><h2>Critérios de aceite</h2></div><p class="work-prose">{{ detail.dossier.acceptance }}</p></section>
        <section v-if="detail.decisions?.length" class="work-section"><div class="work-section-header"><h2>Decisões</h2></div><DecisionRequest v-for="decision in detail.decisions" :key="decision.id" :decision="decision" @answered="load" @stale="load" /></section>
        <section class="work-section"><div class="work-section-header"><h2>Execuções</h2><span class="work-muted">{{ detail.attempts.length }} tentativas</span></div><AttemptResult v-for="attempt in detail.attempts" :key="attempt.id" :attempt="attempt" live /><p v-if="!detail.attempts.length" class="work-muted">O andamento aparecerá aqui quando um trabalhador iniciar.</p></section>
        <section v-if="detail.reviews?.length" class="work-section"><div class="work-section-header"><h2>Revisão independente</h2></div><ReviewRecord v-for="(review, index) in detail.reviews" :key="index" :review="review" /></section>
        <TaskPullRequests v-if="detail.pull_requests?.items.length" :page="detail.pull_requests" />
        <TaskActivity :key="detail.item.id" :item-id="detail.item.id" :events="detail.events" :page="detail.events_page" />
      </div><aside><dl class="work-facts"><div><dt>Projeto</dt><dd><RouterLink class="work-link" :to="`/projects/${detail.item.project_id}`">{{ projects.byId(detail.item.project_id)?.name ?? detail.item.project_id }}</RouterLink></dd></div><div><dt>Responsável</dt><dd>{{ detail.attempts.length ? label(detail.attempts[detail.attempts.length - 1]!.role) : 'CTO' }}</dd></div><div><dt>Fase</dt><dd>{{ ({ investigation: 'Investigação', implementation: 'Implementação', testing: 'Teste', review: 'Revisão' } as Record<string,string>)[detail.item.phase] ?? detail.item.phase }}</dd></div><div><dt>Origem</dt><dd>{{ detail.item.source }} {{ detail.item.external_id }}</dd></div><div><dt>Atualizada</dt><dd>{{ when(detail.item.updated_at) }}</dd></div><div><dt>Revisão da tarefa</dt><dd class="font-mono">{{ detail.item.revision }}</dd></div><div v-if="detail.item.parent_id"><dt>Tarefa de origem</dt><dd><RouterLink class="work-link" :to="`/tarefas/${detail.item.parent_id}`">#{{ detail.item.parent_id }}</RouterLink></dd></div><div v-if="detail.dependencies?.length"><dt>Dependências</dt><dd><ul class="task-dependencies"><li v-for="dependency in detail.dependencies" :key="dependency"><RouterLink class="work-link" :to="`/tarefas/${dependency}`">Tarefa #{{ dependency }}</RouterLink></li></ul></dd></div></dl></aside></div>
    </template>
  </WorkPage>
</template>
<style scoped>
.task-top{display:flex;flex-wrap:wrap;align-items:center;gap:18px;margin:6px 0 25px}.task-top>.work-link{font-size:0.75rem}.review-record{font-size:0.75rem;padding:12px 0;border-top:1px solid var(--color-line)}summary{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:0.6875rem;max-height:340px;overflow:auto;line-height:1.7}
</style>
