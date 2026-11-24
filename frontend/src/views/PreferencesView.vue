<script setup lang="ts">
import { computed, nextTick, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppearancePreferences from '../components/preferences/AppearancePreferences.vue'
import ConversationPreferences from '../components/preferences/ConversationPreferences.vue'
import DigestAgentPreferences from '../components/preferences/DigestAgentPreferences.vue'
import ExecutionPreferences from '../components/preferences/ExecutionPreferences.vue'
import GeneralPreferences from '../components/preferences/GeneralPreferences.vue'
import GithubPreferences from '../components/preferences/GithubPreferences.vue'
import LabelPreferences from '../components/preferences/LabelPreferences.vue'
import NotificationPreferences from '../components/preferences/NotificationPreferences.vue'

// Small inline icons keep the tab list scannable; each tab has its own shape.
const GROUPS = [
  {
    label: 'Interface',
    tabs: [
      { id: 'geral', label: 'Geral', test: 'tab-general', icon: 'M4 6h16M4 12h16M4 18h10' },
      { id: 'aparencia', label: 'Aparência', test: 'tab-appearance', icon: 'M12 3a9 9 0 1 0 0 18c1.5 0 2-1 1.4-2.2-.7-1.4.2-2.8 1.6-2.8H17a4 4 0 0 0 4-4c0-5-4-9-9-9Z M7.5 10.5h.01M12 7h.01M16.5 10.5h.01' },
    ],
  },
  {
    label: 'Conversas',
    tabs: [
      { id: 'conversas', label: 'Conversas', test: 'tab-conversations', icon: 'M21 12a8 8 0 0 1-8 8H4l2-3a8 8 0 1 1 15-5Z' },
      { id: 'etiquetas', label: 'Etiquetas', test: 'tab-labels', icon: 'M3 12V5a2 2 0 0 1 2-2h7l9 9-9 9-9-9Z M8 8h.01' },
    ],
  },
  {
    label: 'Agente',
    tabs: [
      { id: 'agente', label: 'Agente de resumos', test: 'tab-agent', icon: 'M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1M9 12a3 3 0 1 0 6 0 3 3 0 0 0-6 0Z' },
      { id: 'execucao', label: 'Execução', test: 'tab-execution', icon: 'M5 4l14 8-14 8V4Z' },
      { id: 'notificacoes', label: 'Notificações', test: 'tab-notifications', icon: 'M6 9a6 6 0 1 1 12 0c0 4 1.5 5.5 2 6H4c.5-.5 2-2 2-6Z M10 19a2 2 0 0 0 4 0' },
    ],
  },
  {
    label: 'Integrações',
    tabs: [
      { id: 'github', label: 'GitHub', test: 'tab-github', icon: 'M12 3a9 9 0 0 0-3.2 17.4c.5.1.7-.2.7-.5v-1.7c-2.8.6-3.4-1.3-3.4-1.3-.5-1.2-1.1-1.5-1.1-1.5-.9-.6.1-.6.1-.6 1 .1 1.5 1 1.5 1 .9 1.5 2.4 1.1 3 .8.1-.7.4-1.1.6-1.4-2.2-.3-4.6-1.1-4.6-5 0-1.1.4-2 1-2.7-.1-.2-.4-1.3.1-2.7 0 0 .8-.3 2.7 1a9.4 9.4 0 0 1 5 0c1.9-1.3 2.7-1 2.7-1 .5 1.4.2 2.5.1 2.7.6.7 1 1.6 1 2.7 0 3.9-2.4 4.7-4.6 5 .4.3.7.9.7 1.9v2.8c0 .3.2.6.7.5A9 9 0 0 0 12 3Z' },
    ],
  },
] as const
const TABS = GROUPS.flatMap((g) => [...g.tabs])
type Tab = (typeof TABS)[number]['id']

const route = useRoute()
const router = useRouter()
const tab = computed<Tab>(() => TABS.find((t) => t.id === route.query.aba)?.id ?? 'geral')

async function focusAuthentication() {
  if (route.hash !== '#claude-authentication' || tab.value !== 'conversas') return
  await nextTick()
  const section = document.getElementById('claude-authentication')
  section?.focus({ preventScroll: true })
  section?.scrollIntoView({ block: 'center' })
}
onMounted(focusAuthentication)
watch(() => route.fullPath, focusAuthentication, { flush: 'post' })

function select(id: Tab) {
  if (id === tab.value) return
  void router.replace({ query: { ...route.query, aba: id === 'geral' ? undefined : id } })
}

function onKey(event: KeyboardEvent) {
  const forward = event.key === 'ArrowRight' || event.key === 'ArrowDown'
  const back = event.key === 'ArrowLeft' || event.key === 'ArrowUp'
  if (!forward && !back) return
  event.preventDefault()
  const index = TABS.findIndex((t) => t.id === tab.value)
  const next = TABS[(index + (forward ? 1 : TABS.length - 1)) % TABS.length]
  select(next.id)
  requestAnimationFrame(() => document.getElementById(`tab-${next.id}`)?.focus())
}
</script>

<template>
  <div class="flex min-h-full items-start justify-center px-6 py-10 lg:px-10 2xl:px-16">
    <div class="flex w-full max-w-[1100px] flex-col rounded-xl border border-line-strong bg-panel xl:max-w-[1360px] 2xl:max-w-none">
      <header class="flex flex-col gap-1 border-b border-line px-7 py-6">
        <h1 id="preferences-title" class="m-0 text-[1.375rem] font-semibold tracking-tight">Preferências</h1>
        <p class="m-0 text-fg-muted">Ajustes do app neste computador, agrupados por assunto.</p>
      </header>
      <div class="flex flex-col md:flex-row">
        <nav
          role="tablist"
          aria-labelledby="preferences-title"
          aria-orientation="vertical"
          class="flex shrink-0 flex-col gap-5 border-b border-line p-4 md:w-52 md:border-r md:border-b-0 xl:w-60"
          @keydown="onKey"
        >
          <div v-for="group in GROUPS" :key="group.label" role="presentation" class="flex flex-col gap-0.5">
            <p class="m-0 px-3 pb-1 text-[0.6875rem] font-semibold tracking-[0.08em] text-fg-subtle uppercase">
              {{ group.label }}
            </p>
            <button
              v-for="t in group.tabs"
              :id="`tab-${t.id}`"
              :key="t.id"
              type="button"
              role="tab"
              :data-test="t.test"
              :aria-selected="tab === t.id"
              :aria-controls="`panel-${t.id}`"
              :tabindex="tab === t.id ? 0 : -1"
              class="flex h-9 items-center gap-2 rounded-lg px-3 text-left text-sm font-medium"
              :class="tab === t.id ? 'bg-elevated text-fg' : 'text-fg-muted hover:bg-card hover:text-fg'"
              @click="select(t.id)"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path :d="t.icon" />
              </svg>
              {{ t.label }}
            </button>
          </div>
        </nav>
        <section :id="`panel-${tab}`" role="tabpanel" :aria-labelledby="`tab-${tab}`" class="min-w-0 flex-1">
          <GeneralPreferences v-if="tab === 'geral'" />
          <AppearancePreferences v-else-if="tab === 'aparencia'" />
          <ConversationPreferences v-else-if="tab === 'conversas'" />
          <LabelPreferences v-else-if="tab === 'etiquetas'" />
          <DigestAgentPreferences v-else-if="tab === 'agente'" />
          <ExecutionPreferences v-else-if="tab === 'execucao'" />
          <NotificationPreferences v-else-if="tab === 'notificacoes'" />
          <GithubPreferences v-else />
        </section>
      </div>
    </div>
  </div>
</template>
