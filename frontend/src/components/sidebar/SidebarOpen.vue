<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import SidebarSessionRow from './SidebarSessionRow.vue'
import { OPEN_MAX, nowSessions } from './openList'
import { isSectionCollapsed, setSectionCollapsed } from '../../sidebarCollapse'
import { useSessionsStore } from '../../stores/sessions'
import IconChevron from '../icons/IconChevron.vue'

const sessions = useSessionsStore()
// `all` is newest first; the order keeps that inside each band (waits for you, priority, running, the rest).
// Sessions marked "Para revisar", "Em espera" or "Bloqueada" show in their own lanes, unless Claude has a request.
const open = computed(() => nowSessions(sessions.all))
const shown = computed(() => open.value.slice(0, OPEN_MAX))
const collapsed = computed(() => isSectionCollapsed('open'))
</script>

<template>
  <section v-if="open.length" data-test="sidebar-open" aria-labelledby="sidebar-open-title" class="flex flex-col gap-px">
    <button
      type="button"
      data-test="open-toggle"
      :aria-expanded="!collapsed"
      class="mt-2.5 flex h-[30px] w-full items-center gap-1.5 rounded-md border-none bg-transparent px-2.5 text-left font-mono text-[0.6875rem] tracking-[0.08em] text-fg-subtle uppercase hover:text-fg focus-visible:outline-2 focus-visible:outline-primary"
      @click="setSectionCollapsed('open', !collapsed)"
    >
      <IconChevron :open="!collapsed" :size="12" />
      <span id="sidebar-open-title" class="grow">Abertas</span>
      <span data-test="open-count" class="tracking-normal">{{ open.length }}</span>
    </button>
    <template v-if="!collapsed">
      <SidebarSessionRow v-for="session in shown" :key="session.session_id" data-test="open" :session="session" />
      <RouterLink
        v-if="open.length > OPEN_MAX"
        data-test="open-all"
        to="/sessions?estado=ativas"
        class="px-2.5 py-1 text-xs text-fg-subtle no-underline hover:text-fg"
      >Ver todas</RouterLink>
    </template>
  </section>
</template>
