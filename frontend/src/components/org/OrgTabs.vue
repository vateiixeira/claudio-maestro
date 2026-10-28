<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import RoutinesTab from './routines/RoutinesTab.vue'
import RunsTab from './runs/RunsTab.vue'
import TasksTab from './tasks/TasksTab.vue'

const TABS = [
  { id: 'tarefas', label: 'Tarefas' },
  { id: 'rotinas', label: 'Rotinas' },
  { id: 'execucoes', label: 'Execuções' },
] as const
type TabId = (typeof TABS)[number]['id']

defineProps<{ projectId: number }>()
const route = useRoute()
const router = useRouter()
const buttons = ref<HTMLButtonElement[]>([])

// A missing or unknown `aba` is the first tab.
const active = computed<TabId>(() => TABS.find((t) => t.id === route.query.aba)?.id ?? 'tarefas')

function select(id: TabId): void {
  if (id === active.value && route.query.aba === id) return
  void router.replace({ query: { ...route.query, aba: id } })
}

// Arrow keys move between tabs (the focused tab is the only one in the tab order).
async function onKey(event: KeyboardEvent, index: number): Promise<void> {
  const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
  const target = event.key === 'Home' ? 0 : event.key === 'End' ? TABS.length - 1 : (index + step + TABS.length) % TABS.length
  if (step === 0 && event.key !== 'Home' && event.key !== 'End') return
  event.preventDefault()
  select(TABS[target]!.id)
  await nextTick()
  buttons.value[target]?.focus()
}
</script>

<template>
  <div class="flex min-w-0 flex-col gap-4">
    <div role="tablist" aria-label="Organização" class="flex gap-1 border-b border-line">
      <button
        v-for="(tab, index) in TABS"
        :key="tab.id"
        :ref="(el) => { if (el) buttons[index] = el as HTMLButtonElement }"
        type="button"
        role="tab"
        :id="`org-tab-${tab.id}`"
        :data-test="`org-tab-${tab.id}`"
        :aria-selected="active === tab.id"
        aria-controls="org-tabpanel"
        :tabindex="active === tab.id ? 0 : -1"
        class="-mb-px h-9 cursor-pointer border-0 border-b-2 bg-transparent px-3 text-sm font-medium hover:text-fg focus-visible:outline-2 focus-visible:outline-primary"
        :class="active === tab.id ? 'border-primary text-fg' : 'border-transparent text-fg-muted'"
        @click="select(tab.id)"
        @keydown="onKey($event, index)"
      >{{ tab.label }}</button>
    </div>
    <div id="org-tabpanel" role="tabpanel" :aria-labelledby="`org-tab-${active}`">
      <TasksTab v-if="active === 'tarefas'" :project-id="projectId" />
      <RoutinesTab v-else-if="active === 'rotinas'" :project-id="projectId" />
      <RunsTab v-else :project-id="projectId" />
    </div>
  </div>
</template>
