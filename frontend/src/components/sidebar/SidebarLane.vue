<script setup lang="ts">
import { computed } from 'vue'
import SidebarSessionRow from './SidebarSessionRow.vue'
import { laneSessions } from './openList'
import { isSectionCollapsed, isSectionOpened, setSectionCollapsed, setSectionOpened } from '../../sidebarCollapse'
import { useSessionsStore } from '../../stores/sessions'
import IconChevron from '../icons/IconChevron.vue'

const props = withDefaults(defineProps<{ lane: 'review' | 'later'; title: string; startCollapsed?: boolean }>(), { startCollapsed: false })
const sessions = useSessionsStore()
const list = computed(() => laneSessions(sessions.all, props.lane))
// "Depois" starts collapsed and remembers being opened; "Para revisar" starts open and remembers being collapsed.
const collapsed = computed(() => (props.startCollapsed ? !isSectionOpened(props.lane) : isSectionCollapsed(props.lane)))
function toggle() {
  if (props.startCollapsed) setSectionOpened(props.lane, collapsed.value)
  else setSectionCollapsed(props.lane, !collapsed.value)
}
</script>

<template>
  <section v-if="list.length" :data-test="`lane-${lane}`" :aria-labelledby="`sidebar-lane-${lane}`" class="flex flex-col gap-px">
    <button
      type="button"
      :data-test="`lane-${lane}-toggle`"
      :aria-expanded="!collapsed"
      class="flex h-[30px] w-full items-center gap-1.5 rounded-md border-none bg-transparent px-2.5 text-left font-mono text-[0.6875rem] tracking-[0.08em] text-fg-subtle uppercase hover:text-fg focus-visible:outline-2 focus-visible:outline-primary"
      @click="toggle"
    >
      <IconChevron :open="!collapsed" :size="12" />
      <span :id="`sidebar-lane-${lane}`" class="grow">{{ title }}</span>
      <span :data-test="`lane-${lane}-count`" class="tracking-normal">{{ list.length }}</span>
    </button>
    <template v-if="!collapsed">
      <SidebarSessionRow v-for="session in list" :key="session.session_id" :data-test="`lane-${lane}-row`" :session="session" />
    </template>
  </section>
</template>
