<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import DigestAgentPreferences from '../components/preferences/DigestAgentPreferences.vue'
import ExecutionPreferences from '../components/preferences/ExecutionPreferences.vue'
import GeneralPreferences from '../components/preferences/GeneralPreferences.vue'
import NotificationPreferences from '../components/preferences/NotificationPreferences.vue'

const TABS = [
  { id: 'geral', label: 'Geral', test: 'tab-general' },
  { id: 'agente', label: 'Agente de resumos', test: 'tab-agent' },
  { id: 'execucao', label: 'Execução', test: 'tab-execution' },
  { id: 'notificacoes', label: 'Notificações', test: 'tab-notifications' },
] as const
type Tab = (typeof TABS)[number]['id']

const route = useRoute()
const router = useRouter()
const tab = computed<Tab>(() => TABS.find((t) => t.id === route.query.aba)?.id ?? 'geral')

function select(id: Tab) {
  if (id === tab.value) return
  void router.replace({ query: { ...route.query, aba: id === 'geral' ? undefined : id } })
}

function onKey(event: KeyboardEvent) {
  if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return
  const index = TABS.findIndex((t) => t.id === tab.value)
  const next = TABS[(index + (event.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length]
  select(next.id)
  requestAnimationFrame(() => document.getElementById(`tab-${next.id}`)?.focus())
}
</script>

<template>
  <div class="flex min-h-full items-start justify-center px-6 py-10">
    <div class="flex w-full max-w-[720px] flex-col rounded-xl border border-line-strong bg-panel">
      <header class="flex flex-col gap-4 border-b border-line px-7 pt-6">
        <div class="flex flex-col gap-1">
          <h1 id="preferences-title" class="m-0 text-[1.375rem] font-semibold tracking-tight">Preferências</h1>
          <p class="m-0 text-fg-muted">Ajustes do app neste computador.</p>
        </div>
        <div role="tablist" aria-labelledby="preferences-title" class="-mb-px flex gap-1" @keydown="onKey">
          <button
            v-for="t in TABS"
            :id="`tab-${t.id}`"
            :key="t.id"
            type="button"
            role="tab"
            :data-test="t.test"
            :aria-selected="tab === t.id"
            :aria-controls="`panel-${t.id}`"
            :tabindex="tab === t.id ? 0 : -1"
            class="h-10 border-b-2 px-3 text-sm font-medium"
            :class="tab === t.id ? 'border-fg text-fg' : 'border-transparent text-fg-muted hover:text-fg'"
            @click="select(t.id)"
          >{{ t.label }}</button>
        </div>
      </header>
      <section :id="`panel-${tab}`" role="tabpanel" :aria-labelledby="`tab-${tab}`">
        <GeneralPreferences v-if="tab === 'geral'" />
        <DigestAgentPreferences v-else-if="tab === 'agente'" />
        <ExecutionPreferences v-else-if="tab === 'execucao'" />
        <NotificationPreferences v-else />
      </section>
    </div>
  </div>
</template>
