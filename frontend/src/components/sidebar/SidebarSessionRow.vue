<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import ClosureBadge from '../ClosureBadge.vue'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import LabelBadges from '../labels/LabelBadges.vue'
import MarkIcon from '../MarkIcon.vue'
import SessionActivity from '../conversation/SessionActivity.vue'
import MarkPopover from '../marks/MarkPopover.vue'
import { contextPoint } from '../marks/menuPoint'
import { isQuietSession, sidebarItemClass, sidebarNestedItemClass } from './itemClass'
import { markChipText, markLabels, untilShort } from '../../conversation/marks'
import { formatActivity, formatElapsedShort } from '../../format'
import { useMinuteClock } from '../../minuteClock'
import { useLabelsStore } from '../../stores/labels'
import { useProjectsStore } from '../../stores/projects'
import { worktreeLabel } from '../../worktree'
import type { Session } from '../../types/api'

const props = withDefaults(defineProps<{ session: Session; hideProject?: boolean; nested?: boolean }>(), { hideProject: false, nested: false })
const route = useRoute()
const projects = useProjectsStore()
const labels = useLabelsStore()
const project = computed(() => projects.byId(props.session.project_id))
const worktree = computed(() => worktreeLabel(props.session))
const active = computed(() => route.name === 'session' && route.params.id === props.session.session_id)
const prominent = computed(() => props.session.display_state === 'running' || (props.session.display_state === 'waiting' && !isQuietSession(props.session)))
const now = useMinuteClock()
const age = computed(() => formatElapsedShort(props.session.last_activity_at, now.value))
const markTitle = computed(() => markChipText(props.session, new Date(now.value)) ?? undefined)
const until = computed(() =>
  props.session.mark === 'on_hold' && props.session.mark_until ? untilShort(props.session.mark_until, new Date(now.value)) : null,
)
const menuAt = ref<{ x: number; y: number } | null>(null)
// Labels the store knows; without them (and without activity) the row is just its title line.
const hasLabels = computed(() => (props.session.label_ids ?? []).some((id) => labels.byId(id) !== undefined))
const rowClass = computed(() =>
  props.nested ? sidebarNestedItemClass(active.value, prominent.value, true) : sidebarItemClass(active.value, true),
)
// What is new gets the strong color and a medium weight; the rest takes the dimmer color of the row.
const titleClass = computed(() => [
  'min-w-0 grow truncate',
  props.nested ? 'text-[0.78125rem]' : 'text-[0.8125rem]',
  props.session.unread ? 'font-medium text-fg' : '',
])
</script>

<template>
  <RouterLink
    :to="{ name: 'session', params: { id: session.session_id } }"
    :class="rowClass"
    :aria-current="active ? 'page' : undefined"
    @contextmenu.prevent="menuAt = contextPoint($event)"
  >
    <span class="flex h-5 items-center"><DisplayStateIcon :display="session.display_state" :size="nested ? 10 : 11" :quiet="isQuietSession(session)" /></span>
    <span data-test="row-line" :class="['flex min-h-5 min-w-0 items-center', nested ? 'gap-2' : 'gap-2.5']">
      <span data-test="row-title" :class="titleClass">{{ session.title }}</span>
      <span
        data-test="row-age"
        :title="`Última interação ${formatActivity(session.last_activity_at)}`"
        class="shrink-0 font-mono text-[0.6875rem] text-fg-subtle tabular-nums"
      >{{ age }}</span>
      <span v-if="until" data-test="row-until" class="shrink-0 font-mono text-[0.6875rem] text-fg-subtle">{{ until }}</span>
      <span v-if="session.mark" data-test="row-mark" role="img" :title="markTitle" :aria-label="markLabels[session.mark]" class="shrink-0 text-fg-subtle"><MarkIcon :mark="session.mark" /></span>
      <span v-if="session.priority" data-test="row-priority" role="img" title="Prioridade" aria-label="Prioridade" class="shrink-0 text-fg-muted"><MarkIcon mark="priority" /></span>
      <ClosureBadge :session="session" compact />
      <span
        v-if="project && !hideProject"
        data-test="row-project"
        :title="project.name"
        class="size-2 shrink-0 rounded-[2px]"
        :style="{ backgroundColor: project.color }"
      ><span class="sr-only">{{ project.name }}</span></span>
      <span v-if="worktree" data-test="row-worktree" :title="worktree" :aria-label="worktree" class="shrink-0 text-fg-muted">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /><path d="M6.5 10v4a3 3 0 0 0 3 3H14" />
        </svg>
      </span>
    </span>
    <SessionActivity data-test="row-activity" :session="session" class="col-start-2" />
    <span v-if="hasLabels" data-test="row-labels" class="col-start-2 flex min-w-0">
      <LabelBadges :ids="session.label_ids" compact wrap />
    </span>
    <!-- Teleported to the body, so the row keeps a single root and the attributes its parents pass. -->
    <MarkPopover v-if="menuAt" :session="session" :x="menuAt.x" :y="menuAt.y" @close="menuAt = null" />
  </RouterLink>
</template>
