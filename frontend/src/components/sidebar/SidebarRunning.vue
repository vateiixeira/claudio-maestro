<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import SidebarSessionRow from './SidebarSessionRow.vue'
import { useSessionsStore } from '../../stores/sessions'

const RUNNING_MAX = 8
const sessions = useSessionsStore()
// `all` is already newest first; the CLI mid-turn counts as running (display_state).
const running = computed(() => sessions.all.filter((s) => s.display_state === 'running'))
const shown = computed(() => running.value.slice(0, RUNNING_MAX))
</script>

<template>
  <div v-if="running.length" data-test="sidebar-running" class="flex flex-col gap-1">
    <div class="px-3 pt-4 pb-0.5 font-mono text-xs tracking-[0.08em] text-fg-subtle uppercase">Em execução</div>
    <SidebarSessionRow v-for="session in shown" :key="session.session_id" data-test="running" :session="session" />
    <RouterLink
      v-if="running.length > RUNNING_MAX"
      data-test="running-all"
      :to="{ name: 'inbox', query: { aba: 'em-execucao' } }"
      class="px-3 py-1 text-xs text-fg-subtle no-underline hover:text-fg"
    >Ver todas</RouterLink>
  </div>
</template>
