<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink, type RouteLocationRaw } from 'vue-router'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import MarkIcon from '../MarkIcon.vue'
import MarkPopover from '../marks/MarkPopover.vue'
import { contextPoint } from '../marks/menuPoint'
import ClosureBadge from '../ClosureBadge.vue'
import BranchLabel from '../git/BranchLabel.vue'
import GroupTag from '../groups/GroupTag.vue'
import WorktreeLabel from '../git/WorktreeLabel.vue'
import PlanBadge from '../plan/PlanBadge.vue'
import { errorMessage, markSessionSeen } from '../../api/http'
import { markChipText, markLabels } from '../../conversation/marks'
import { waitingReason } from '../../conversationList'
import { needsYou } from '../../conversation/needsYou'
import { formatActivity } from '../../format'
import { planPosition, planVisible } from '../plan/planText'
import { displayStateLabel } from '../../sessionState'
import { repoLabel, useGitStore } from '../../stores/git'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import type { Session } from '../../types/api'
import { worktreeLabel } from '../../worktree'

// One conversation in a list. `inbox` adds "Marcar como lida"; `compact` has no actions.
// `to` replaces the link's destination (still a link, so middle-click opens a tab); `active` marks the open row.
// `focused` is the keyboard cursor of a list (same look as `active`, with the actions always shown). The `actions` slot
// adds buttons before the usual ones; the `status` slot takes the place of the waiting reason.
const props = withDefaults(
  defineProps<{ session: Session; variant?: 'inbox' | 'list' | 'compact'; to?: RouteLocationRaw; active?: boolean; focused?: boolean }>(),
  { variant: 'list' },
)
const target = computed<RouteLocationRaw>(() => props.to ?? { name: 'session', params: { id: props.session.session_id } })
const emit = defineEmits<{ error: [message: string] }>()

const projects = useProjectsStore()
const git = useGitStore()
const sessions = useSessionsStore()

const project = computed(() => projects.byId(props.session.project_id))
const repo = computed(() => git.reposFor(props.session.project_id)[0])
const worktree = computed(() => worktreeLabel(props.session))
const finished = computed(() => props.session.display_state === 'finished')
const reason = computed(() => waitingReason(props.session))
const wantsYou = computed(() => needsYou(props.session))
const compact = computed(() => props.variant === 'compact')
// The compact row hides the visible reason, so screen readers still get it.
const srState = computed(() => {
  const label = displayStateLabel(props.session)
  return compact.value && reason.value && reason.value !== label ? `${label}: ${reason.value}` : label
})
// The link's stretched ::after covers the badge, so the badge's own title never shows: repeat it on the link.
const planTitle = computed(() => (!compact.value && planVisible(props.session) ? planPosition(props.session.plan!) : undefined))
const busy = ref(false)
const menuAt = ref<{ x: number; y: number } | null>(null)
// Same reason for the mark's note ("Bloqueada: ..."): its icon sits under the link's ::after.
const markTitle = computed(() => markChipText(props.session, new Date()) ?? undefined)
const linkTitle = computed(() => [markTitle.value, planTitle.value].filter(Boolean).join(' · ') || undefined)

async function run(action: () => Promise<unknown>) {
  if (busy.value) return
  busy.value = true
  try {
    await action()
  } catch (e) {
    emit('error', errorMessage(e))
  } finally {
    busy.value = false
  }
}
const toggleFinished = () => run(() => sessions.setFinished(props.session.session_id, !finished.value))
const markRead = () => run(() => markSessionSeen(props.session.session_id))
</script>

<template>
  <div
    data-test="conversation-row"
    :data-unread="String(session.unread)"
    :data-active="active ? 'true' : undefined"
    :data-focused="focused ? 'true' : undefined"
    @contextmenu.prevent="menuAt = contextPoint($event)"
    class="group relative flex min-h-11 items-center gap-3 rounded-md px-2 hover:bg-card focus-within:bg-card"
    :class="active || focused ? 'bg-card shadow-[inset_2px_0_0_var(--color-primary)]' : ''"
  >
    <span class="flex w-2 shrink-0 justify-center">
      <span v-if="session.unread" data-test="unread-dot" class="size-2 rounded-full bg-info" />
    </span>
    <DisplayStateIcon :display="session.display_state" :quiet="!wantsYou" />
    <span v-if="session.mark" data-test="row-mark" role="img" :aria-label="markLabels[session.mark]" class="shrink-0 text-fg-subtle"><MarkIcon :mark="session.mark" /></span>
    <span v-if="session.priority" data-test="row-priority" role="img" title="Prioridade" aria-label="Prioridade" class="shrink-0 text-fg-muted"><MarkIcon mark="priority" /></span>
    <!-- Not positioned, so the link's stretched ::after still covers the whole row. -->
    <div data-test="row-title" class="flex grow items-center gap-2" :class="compact ? 'min-w-24 overflow-hidden' : 'min-w-0'">
      <RouterLink
        data-test="row-link"
        :to="target"
        :aria-current="active ? 'true' : undefined"
        :title="linkTitle"
        class="min-w-0 truncate no-underline after:absolute after:inset-0 after:rounded-md focus-visible:outline-none focus-visible:after:ring-2 focus-visible:after:ring-primary focus-visible:after:ring-inset"
        :class="[finished ? 'text-fg-muted' : 'text-fg', session.unread ? 'font-semibold' : 'font-normal', session.digest_short && !compact ? 'max-w-[55%] shrink-0' : '']"
      >{{ session.title }}</RouterLink>
      <PlanBadge v-if="!compact" :session="session" />
      <GroupTag v-if="!compact" :group-id="session.group_id" />
      <span
        v-if="session.plan_done && !compact"
        data-test="row-plan-done"
        class="shrink-0 rounded-full border border-primary/40 px-1.5 font-mono text-[0.6875rem] text-primary-soft"
      >Plano concluído</span>
      <ClosureBadge :session="session" :compact="compact" />
      <span
        v-if="session.digest_short && !compact"
        data-test="row-digest"
        class="min-w-0 truncate text-xs text-fg-muted"
      >{{ session.digest_short }}</span>
    </div>
    <span class="sr-only">{{ srState }}{{ session.unread ? ', com novidade' : '' }}</span>
    <slot name="status">
      <span v-if="reason && !compact" data-test="waiting-reason" class="max-w-64 shrink-0 truncate text-xs" :class="wantsYou ? 'text-secondary-soft' : 'text-fg-muted'">{{ reason }}</span>
    </slot>
    <!-- Fixed widths, kept even when empty, so the columns line up from row to row. The actions float over the right end instead of taking room from them. -->
    <span data-test="row-project" class="hidden items-center gap-1.5 text-xs text-fg-subtle md:flex" :class="compact ? 'w-28 min-w-0 shrink' : 'w-36 shrink-0'">
      <template v-if="project">
        <span class="size-2 shrink-0 rounded-[3px]" :style="{ backgroundColor: project.color }" />
        <span class="truncate">{{ project.name }}</span>
      </template>
    </span>
    <span v-if="!compact" data-test="row-branch" class="hidden w-40 shrink-0 lg:flex">
      <WorktreeLabel v-if="worktree" :text="worktree" muted />
      <BranchLabel v-else-if="repo" :text="repoLabel(repo)" muted />
    </span>
    <span class="shrink-0 whitespace-nowrap text-right text-xs text-fg-subtle" :class="compact ? 'min-w-12' : 'w-20'">{{ formatActivity(session.last_activity_at) }}</span>
    <div
      v-if="variant !== 'compact'"
      data-test="row-actions"
      class="absolute inset-y-0 right-2 z-10 flex items-center gap-1 rounded-md bg-card pl-2 group-hover:opacity-100 group-hover:pointer-events-auto group-focus-within:opacity-100 group-focus-within:pointer-events-auto focus-within:opacity-100 focus-within:pointer-events-auto [@media(hover:none)]:opacity-100 [@media(hover:none)]:pointer-events-auto"
      :class="focused ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'"
    >
      <slot name="actions" />
      <button
        v-if="variant === 'inbox' && session.unread"
        type="button"
        data-test="row-mark-read"
        class="h-8 rounded-md px-2 text-xs text-fg-muted hover:bg-elevated hover:text-fg disabled:opacity-40"
        :disabled="busy"
        :aria-label="`Marcar ${session.title} como lida`"
        @click="markRead"
      >Marcar como lida</button>
      <button
        v-if="finished"
        type="button"
        data-test="row-reopen"
        class="h-8 rounded-md px-2 text-xs font-medium text-primary-soft hover:bg-elevated disabled:opacity-40"
        :disabled="busy"
        :aria-label="`Reabrir ${session.title}`"
        @click="toggleFinished"
      >Reabrir</button>
      <button
        v-else
        type="button"
        data-test="row-finish"
        class="h-8 rounded-md px-2 text-xs text-fg-muted hover:bg-elevated hover:text-fg disabled:opacity-40"
        :disabled="busy"
        :aria-label="`Finalizar ${session.title}`"
        @click="toggleFinished"
      >Finalizar</button>
    </div>
    <MarkPopover v-if="menuAt" :session="session" :x="menuAt.x" :y="menuAt.y" @close="menuAt = null" />
  </div>
</template>
