<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import { isQuietSession } from './itemClass'
import { isCollapsed, setCollapsed } from '../../sidebarCollapse'
import { projectTree } from '../../sidebarTree'
import { useGroupsStore } from '../../stores/groups'
import { useSessionsStore } from '../../stores/sessions'
import IconChevron from '../icons/IconChevron.vue'
import IconGroup from '../icons/IconGroup.vue'

const props = defineProps<{ projectId: number }>()
const groups = useGroupsStore()
const sessions = useSessionsStore()
const route = useRoute()

const tree = computed(() => projectTree(groups.forProject(props.projectId), sessions.forProject(props.projectId)))
const isCurrent = (id: string) => route.name === 'session' && route.params.id === id
const rowClass = 'flex min-h-9 items-center gap-2 rounded-lg px-2 no-underline hover:bg-card'
</script>

<template>
  <div class="flex flex-col gap-0.5 pl-6">
    <div v-for="item in tree.active" :key="item.group.id" data-test="sidebar-group" class="flex flex-col">
      <button
        type="button"
        data-test="group-toggle"
        :aria-expanded="!isCollapsed('group', item.group.id)"
        :class="rowClass"
        class="w-full text-left text-fg-muted hover:text-fg"
        @click="setCollapsed('group', item.group.id, !isCollapsed('group', item.group.id))"
      >
        <IconChevron :open="!isCollapsed('group', item.group.id)" :size="12" />
        <IconGroup :size="12" class="shrink-0" />
        <span class="min-w-0 grow truncate text-[13px]">{{ item.group.name }}</span>
        <span v-if="item.waiting" data-test="group-waiting" class="flex items-center gap-1 text-xs text-secondary">
          <DisplayStateIcon display="waiting" :size="11" />{{ item.waiting }}
        </span>
      </button>
      <template v-if="!isCollapsed('group', item.group.id)">
        <RouterLink
          v-for="s in item.sessions"
          :key="s.session_id"
          data-test="sidebar-session"
          :to="{ name: 'session', params: { id: s.session_id } }"
          :aria-current="isCurrent(s.session_id) ? 'page' : undefined"
          :class="[rowClass, 'pl-7', isCurrent(s.session_id) ? 'bg-card text-fg' : 'text-fg-muted hover:text-fg']"
        >
          <DisplayStateIcon :display="s.display_state" :size="11" :quiet="isQuietSession(s)" />
          <span class="min-w-0 grow truncate text-[13px]">{{ s.title }}</span>
        </RouterLink>
      </template>
    </div>
    <RouterLink
      v-for="g in tree.idle"
      :key="g.id"
      data-test="sidebar-group-idle"
      :to="{ name: 'project', params: { id: projectId } }"
      :title="`${g.name}: sem conversas ativas`"
      :class="[rowClass, 'text-fg-subtle hover:text-fg']"
    >
      <span aria-hidden="true" class="w-3" />
      <IconGroup :size="12" class="shrink-0" />
      <span class="min-w-0 grow truncate text-[13px]">{{ g.name }}</span>
    </RouterLink>
  </div>
</template>
