<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { errorMessage } from '../api/http'
import { useWorkStore } from '../stores/work'
import { useProjectsStore } from '../stores/projects'
import type { WorkPage as Page } from '../types/work'
import { workStatus } from '../types/work'
import WorkPage from '../components/work/WorkPage.vue'
import TaskRow from '../components/work/TaskRow.vue'
const route = useRoute(), router = useRouter(), work = useWorkStore(), projects = useProjectsStore()
const page = ref<Page>({ items: [], total: 0, limit: 30, offset: 0 }), loading = ref(true), error = ref('')
const projectId = computed(() => Number(route.query.project) || undefined)
const status = computed(() => typeof route.query.status === 'string' ? route.query.status : '')
const source = computed(() => typeof route.query.source === 'string' ? route.query.source : '')
const number = computed(() => Math.max(1, Number(route.query.page) || 1))
let ticket = 0
async function load() {
  const mine = ++ticket; loading.value = true; error.value = ''
  try { const result = await work.list({ project_id: projectId.value, status: status.value, source: source.value, limit: 30, offset: (number.value - 1) * 30 }); if (mine === ticket) page.value = result }
  catch (e) { if (mine === ticket) error.value = errorMessage(e) }
  finally { if (mine === ticket) loading.value = false }
}
function filter(key: string, value: string) { void router.push({ query: { ...route.query, [key]: value || undefined, page: undefined } }) }
function go(n: number) { void router.push({ query: { ...route.query, page: n > 1 ? String(n) : undefined } }) }
watch(() => [route.fullPath, work.changeVersion], () => { void load() }, { immediate: true })
onBeforeUnmount(() => ticket++)
</script>
<template>
  <WorkPage title="Tarefas" eyebrow="Do objetivo à entrega">
    <template #actions><RouterLink class="work-button" :to="{ name: 'cto', query: projectId ? { projeto: projectId } : {} }">Conversar com CTO ↗</RouterLink></template>
    <div class="work-filters">
      <label class="work-filter">Projeto<select class="work-select" :value="projectId ?? ''" @change="filter('project', ($event.target as HTMLSelectElement).value)"><option value="">Todos os projetos</option><option v-for="project in projects.projects" :key="project.id" :value="project.id">{{ project.name }}</option></select></label>
      <label class="work-filter">Estado<select class="work-select" :value="status" @change="filter('status', ($event.target as HTMLSelectElement).value)"><option value="">Todos os estados</option><option v-for="s in ['backlog','ready','active','waiting','blocked','review','done','cancelled']" :key="s" :value="s">{{ workStatus[s] }}</option></select></label>
      <label class="work-filter">Fonte<select class="work-select" :value="source" @change="filter('source', ($event.target as HTMLSelectElement).value)"><option value="">Todas as fontes</option><option value="manual">Objetivos</option><option value="sentry">Sentry</option><option value="kbgen">KBGen</option><option v-if="source && !['manual','sentry','kbgen'].includes(source)" :value="source">{{ source }}</option></select></label>
    </div>
    <p v-if="error" class="work-error" role="alert">{{ error }} <button class="work-button" type="button" @click="load">Tentar novamente</button></p>
    <div v-if="loading" class="work-skeleton" role="status"><span class="sr-only">Carregando tarefas…</span><span /><span /><span /></div>
    <template v-else>
      <div v-if="!page.items.length && !error" class="work-empty"><strong>{{ page.total ? 'Nenhuma tarefa nesta página' : 'Nenhuma tarefa com estes filtros' }}</strong>Entregue um objetivo ao CTO ou ajuste os filtros para acompanhar o trabalho.</div>
      <TaskRow v-for="item in page.items" :key="item.id" :item="item" />
    </template>
    <footer class="work-pagination"><span data-test="work-total" class="work-muted">{{ page.total }} {{ page.total === 1 ? 'tarefa' : 'tarefas' }}<span v-if="page.total"> · Página {{ number }} de {{ Math.max(1, Math.ceil(page.total / 30)) }}</span></span><div class="work-pagination-controls"><button class="work-button" :disabled="loading || number <= 1" @click="go(number - 1)">← Anterior</button><button data-test="work-next" class="work-button" :disabled="loading || number * 30 >= page.total" @click="go(number + 1)">Próxima →</button></div></footer>
  </WorkPage>
</template>
