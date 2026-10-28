<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import OrgTreeNode from './OrgTreeNode.vue'
import { BTN_PRIMARY } from './styles'
import { useOrgStore } from '../../stores/org'

const props = defineProps<{ projectId: number }>()
const emit = defineEmits<{ create: [] }>()
const org = useOrgStore()
const route = useRoute()

const nodes = computed(() => org.tree(props.projectId))
const selectedId = computed(() => {
  const raw = route.query.agente
  const n = typeof raw === 'string' ? Number(raw) : NaN
  return Number.isInteger(n) ? n : null
})
</script>

<template>
  <div>
    <ul v-if="nodes.length" aria-label="Agentes do projeto" class="m-0 flex flex-col gap-px p-0">
      <OrgTreeNode v-for="node in nodes" :key="node.agent.id" :node="node" :selected-id="selectedId" />
    </ul>
    <div v-else-if="org.loaded" data-test="org-tree-empty" class="flex flex-col items-start gap-3 px-2 py-3">
      <p class="m-0 text-sm text-fg-muted">Nenhum agente ainda. Crie o primeiro: um CTO para este projeto.</p>
      <button type="button" data-test="org-tree-create" :class="BTN_PRIMARY" @click="emit('create')">Novo agente</button>
    </div>
    <p v-else role="status" class="m-0 px-2 py-3 text-sm text-fg-subtle">Carregando agentes…</p>
  </div>
</template>
