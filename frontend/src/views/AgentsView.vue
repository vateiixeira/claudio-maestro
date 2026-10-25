<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import AgentDetail from '../components/agents/AgentDetail.vue'
import AgentList from '../components/agents/AgentList.vue'
import AgentsGithub from '../components/agents/AgentsGithub.vue'
import NewAgentDialog from '../components/agents/NewAgentDialog.vue'
import { useSpecialistsStore } from '../stores/specialists'
import type { Specialist } from '../types/api'

const props = defineProps<{ id?: string }>()
const store = useSpecialistsStore()
const router = useRouter()
const route = useRoute()
const githubOpen = computed(() => route.query.github === '1')
function openGithub() {
  void router.push({ name: 'agents', query: { github: '1' } })
}

const selectedId = computed(() => {
  const n = Number(props.id)
  return props.id !== undefined && Number.isInteger(n) ? n : null
})
const selected = computed(() => (selectedId.value === null ? undefined : store.byId(selectedId.value)))

const creating = ref(false)
function created(agent: Specialist): void {
  creating.value = false
  void router.push({ name: 'agents', params: { id: agent.id } })
}

onMounted(() => { void store.load() })
</script>

<template>
  <div class="@container h-full min-h-0 min-w-0">
    <!-- Container queries: what counts is the width of this area (the sidebar already took its share), not the window.
         Narrow, the list sits above the detail; from 56rem on, beside it. -->
    <div class="grid h-full min-h-0 grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)] @4xl:grid-cols-[17rem_minmax(0,1fr)] @4xl:grid-rows-[minmax(0,1fr)]">
    <AgentList :agents="store.list" :selected-id="selectedId" :loading="!store.loaded" @new="creating = true" @github="openGithub" />
    <section aria-label="Detalhe do agente" class="min-h-0 min-w-0 overflow-y-auto p-4 @4xl:p-6">
      <p v-if="store.error" role="alert" class="m-0 mb-4 text-sm text-diff-del-fg">Não foi possível carregar os agentes. {{ store.error }}</p>
      <AgentsGithub v-if="githubOpen" />
      <AgentDetail v-else-if="selected" :key="selected.id" :agent="selected" />
      <p v-else-if="selectedId !== null && store.loaded && !store.error" data-test="agent-missing" class="m-0 text-sm text-fg-muted">
        Agente não encontrado. <RouterLink :to="{ name: 'agents' }" class="text-info-soft hover:text-fg">Voltar à lista</RouterLink>
      </p>
      <div v-else-if="selectedId === null && store.loaded" class="flex flex-col gap-6">
        <p data-test="agent-empty-detail" class="m-0 text-sm text-fg-muted">Escolha um agente na lista ou crie um novo.</p>
        <AgentsGithub />
      </div>
    </section>
    <NewAgentDialog v-if="creating" @created="created" @cancel="creating = false" />
    </div>
  </div>
</template>
