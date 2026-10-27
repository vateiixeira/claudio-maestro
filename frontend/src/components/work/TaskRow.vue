<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { useProjectsStore } from '../../stores/projects'
import type { WorkItem } from '../../types/work'
import WorkStatus from './WorkStatus.vue'
import IconArrowUp from '../icons/IconArrowUp.vue'
defineProps<{ item: WorkItem }>()
const projects = useProjectsStore()
</script>
<template><RouterLink :to="`/tarefas/${item.id}`" class="work-row" data-test="task-row"><span><span class="work-row-title">{{ item.title }}</span><span class="work-row-meta"><span class="font-mono">#{{ item.id }}</span><span>{{ item.source === 'manual' ? 'Objetivo' : item.source }}{{ item.external_id ? ` · ${item.external_id}` : '' }}</span><span v-if="item.priority === 'high' || item.priority === 'urgent'" class="inline-flex items-center gap-1"><IconArrowUp :size="12" /> Prioridade {{ item.priority === 'urgent' ? 'urgente' : 'alta' }}</span></span></span><WorkStatus :status="item.status" /><span class="work-row-project work-muted">{{ projects.byId(item.project_id)?.name ?? `Projeto ${item.project_id}` }}</span></RouterLink></template>
