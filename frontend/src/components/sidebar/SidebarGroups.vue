<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import SidebarSessionRow from './SidebarSessionRow.vue'
import { isDiscarded } from '../../conversation/marks'
import { needsYou } from '../../conversation/needsYou'
import { isCollapsed, setCollapsed } from '../../sidebarCollapse'
import { sidebarFilter } from '../../sidebarFilter'
import { filteredProjectTree } from '../../sidebarTree'
import { sessionsOf } from '../../groupList'
import { useGroupsStore } from '../../stores/groups'
import { useSessionsStore } from '../../stores/sessions'
import type { SessionGroup } from '../../types/api'
import GroupRemoveConfirm from '../groups/GroupRemoveConfirm.vue'
import IconChevron from '../icons/IconChevron.vue'
import IconClose from '../icons/IconClose.vue'
import IconGroup from '../icons/IconGroup.vue'

const props = defineProps<{ projectId: number }>()
const groups = useGroupsStore()
const sessions = useSessionsStore()

// A group created in another project can hold conversations from several: the tree lists all of them.
// With the sidebar filter on, only the ones that match; a group with none is left out.
const tree = computed(() => {
  const filter = sidebarFilter.value
  return filteredProjectTree(groups.visibleIn(props.projectId, sessions.all), sessions.all, filter).map((item) => ({
    ...item,
    // The badge counts what the group shows.
    waiting: item.sessions.filter((s) => s.display_state === 'waiting' && needsYou(s)).length,
  }))
})
const membersOf = (group: SessionGroup) => sessionsOf(group.id, sessions.all.filter((s) => !isDiscarded(s)))

const confirmingId = ref<number | null>(null)
const removeError = ref<string | null>(null)
function openRemove(groupId: number) {
  removeError.value = null
  confirmingId.value = groupId
}
const removeButtons = ref<Record<number, HTMLButtonElement | null>>({})
async function cancelRemove(groupId: number) {
  confirmingId.value = null
  await nextTick()
  removeButtons.value[groupId]?.focus()
}
const removeClass =
  'flex size-6 shrink-0 items-center justify-center rounded-md text-fg-subtle opacity-0 hover:bg-elevated hover:text-fg ' +
  'focus-visible:opacity-100 group-hover/row:opacity-100 group-focus-within/row:opacity-100 pointer-coarse:opacity-100'
const rowClass = 'flex min-h-[30px] items-center gap-2 rounded-lg px-2 no-underline hover:bg-card'
</script>

<template>
  <div class="flex flex-col gap-0.5 pl-6">
    <p v-if="removeError" role="alert" class="m-0 px-2 py-1 text-xs text-diff-del-fg">{{ removeError }}</p>
    <div v-for="item in tree" :key="item.group.id" data-test="sidebar-group" class="flex flex-col">
      <div class="group/row flex items-center">
        <button
          type="button"
          data-test="group-toggle"
          :aria-expanded="!isCollapsed('group', item.group.id)"
          :class="rowClass"
          class="min-w-0 grow text-left text-fg-muted hover:text-fg"
          @click="setCollapsed('group', item.group.id, !isCollapsed('group', item.group.id))"
        >
          <IconChevron :open="!isCollapsed('group', item.group.id)" :size="12" />
          <IconGroup :size="12" class="shrink-0" />
          <span class="min-w-0 grow truncate text-[0.8125rem]">{{ item.group.name }}</span>
          <span v-if="item.waiting" data-test="group-waiting" class="flex items-center gap-1 text-xs text-secondary">
            <DisplayStateIcon display="waiting" :size="11" />{{ item.waiting }}
          </span>
        </button>
        <button
          :ref="(el) => (removeButtons[item.group.id] = el as HTMLButtonElement | null)"
          type="button"
          data-test="sidebar-group-remove"
          :aria-label="`Remover o agrupador ${item.group.name}`"
          :class="removeClass"
          @click="openRemove(item.group.id)"
        ><IconClose :size="12" /></button>
      </div>
      <GroupRemoveConfirm v-if="confirmingId === item.group.id" class="mx-1 my-1" :group="item.group" :sessions="membersOf(item.group)" @cancel="cancelRemove(item.group.id)" @error="removeError = $event" @removed="confirmingId = null" />
      <template v-if="!isCollapsed('group', item.group.id)">
        <SidebarSessionRow
          v-for="s in item.sessions"
          :key="s.session_id"
          data-test="sidebar-session"
          class="ml-5"
          :session="s"
          :hide-project="s.project_id === projectId"
          nested
        />
      </template>
    </div>
  </div>
</template>
