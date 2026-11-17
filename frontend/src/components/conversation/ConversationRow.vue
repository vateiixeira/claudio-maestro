<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink, type RouteLocationRaw } from 'vue-router'
import AgentBadge from '../org/AgentBadge.vue'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import MarkIcon from '../MarkIcon.vue'
import MarkPopover from '../marks/MarkPopover.vue'
import { contextPoint } from '../marks/menuPoint'
import ClosureBadge from '../ClosureBadge.vue'
import GroupTag from '../groups/GroupTag.vue'
import LabelBadges from '../labels/LabelBadges.vue'
import WorktreeLabel from '../git/WorktreeLabel.vue'
import PlanSegments from './PlanSegments.vue'
import ProjectTag from './ProjectTag.vue'
import { errorMessage, markSessionSeen } from '../../api/http'
import { markChipText, markLabels } from '../../conversation/marks'
import { waitingReason } from '../../conversationList'
import { needsYou } from '../../conversation/needsYou'
import { formatActivity } from '../../format'
import { planPosition, planStopped, planVisible } from '../plan/planText'
import { displayStateLabel } from '../../sessionState'
import { repoLabel, useGitStore } from '../../stores/git'
import { useSessionsStore } from '../../stores/sessions'
import type { Session } from '../../types/api'
import { worktreeLabel } from '../../worktree'

// One conversation in a list. `inbox` adds "Marcar como lida".
// `to` replaces the link's destination (still a link, so middle-click opens a tab); `active` marks the open row.
// `focused` is the keyboard cursor of a list (same look as `active`, with the actions always shown). The `actions` slot
// adds buttons before the usual ones; the `status` slot takes the place of the waiting reason.
const props = withDefaults(
  defineProps<{ session: Session; variant?: 'inbox' | 'list'; to?: RouteLocationRaw; active?: boolean; focused?: boolean; projectContextId?: number }>(),
  { variant: 'list' },
)
const target = computed<RouteLocationRaw>(() => props.to ?? { name: 'session', params: { id: props.session.session_id } })
const emit = defineEmits<{ error: [message: string] }>()

const git = useGitStore()
const sessions = useSessionsStore()

const repo = computed(() => git.reposFor(props.session.project_id)[0])
const worktree = computed(() => worktreeLabel(props.session))
const finished = computed(() => props.session.display_state === 'finished')
const planShown = computed(() => planVisible(props.session))
const branchText = computed(() => worktree.value ?? (repo.value ? repoLabel(repo.value) : null))
const reason = computed(() => waitingReason(props.session))
const wantsYou = computed(() => needsYou(props.session))
const projectLayout = computed(() => props.projectContextId != null)
const sameProjectContext = computed(() => props.projectContextId === props.session.project_id)
// The waiting reason is text on the row (`waiting-reason`), so the hidden state only names the state.
const srState = computed(() => displayStateLabel(props.session))
// The link's stretched ::after covers the badge, so the badge's own title never shows: repeat it on the link.
const planTitle = computed(() => (planShown.value ? planPosition(props.session.plan!) : undefined))
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
    class="group relative rounded-md hover:bg-card focus-within:bg-card"
    :class="[
      'grid min-h-[3.375rem] grid-cols-[0.875rem_minmax(0,1fr)_auto] gap-x-4 gap-y-1 px-2.5 py-2',
      projectLayout ? 'items-start py-3 md:grid-cols-[0.875rem_minmax(0,1fr)_15.5rem_4.25rem]' : 'items-center md:grid-cols-[0.875rem_minmax(0,1fr)_11rem_10.5rem_4.25rem]',
      active || focused ? 'bg-card shadow-[inset_2px_0_0_var(--color-primary)]' : '',
    ]"
  >
    <DisplayStateIcon :display="session.display_state" :quiet="!wantsYou" :class="projectLayout ? 'mt-1' : ''" />
    <!-- Not positioned, so the link's stretched ::after still covers the whole row (overflow-hidden only clips descendants whose containing block is inside it, and the ::after's is the row). -->
    <div data-test="row-title" class="flex min-w-0 flex-col gap-1 overflow-hidden">
      <div class="flex min-w-0 items-center gap-1.5">
        <span v-if="session.mark" data-test="row-mark" role="img" :aria-label="markLabels[session.mark]" class="shrink-0 text-fg-subtle"><MarkIcon :mark="session.mark" /></span>
        <span v-if="session.priority" data-test="row-priority" role="img" title="Prioridade" aria-label="Prioridade" class="shrink-0 text-fg-muted"><MarkIcon mark="priority" /></span>
        <RouterLink
          data-test="row-link"
          :to="target"
          :aria-current="active ? 'true' : undefined"
          :title="linkTitle"
          class="min-w-0 truncate text-sm no-underline after:absolute after:inset-0 after:rounded-md focus-visible:outline-none focus-visible:after:ring-2 focus-visible:after:ring-primary focus-visible:after:ring-inset"
          :class="[finished ? 'text-fg-muted' : 'text-fg', session.unread || projectLayout ? 'font-medium' : 'font-normal']"
        >{{ session.title }}</RouterLink>
      </div>
      <div data-test="row-details" class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs empty:hidden">
        <span
          v-if="session.digest_short"
          data-test="row-digest"
          class="min-w-0 basis-full truncate text-fg-muted" :class="projectLayout ? 'text-[0.8125rem]' : 'text-xs'"
        >{{ session.digest_short }}</span>
        <AgentBadge v-if="session.agent_id != null" :agent-id="session.agent_id" />
        <GroupTag :group-id="session.group_id" />
        <LabelBadges :ids="session.label_ids" />
        <span v-if="projectLayout && worktree" data-test="row-branch" class="flex min-w-0 max-w-full text-fg-subtle">
          <WorktreeLabel :text="worktree" muted />
        </span>
        <ProjectTag v-if="projectLayout && !sameProjectContext" :project-id="session.project_id" :branch="branchText" />
      </div>
    </div>
    <span class="sr-only">{{ srState }}{{ session.unread ? ', com novidade' : '' }}</span>
    <div
      data-test="row-situation"
      class="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1 max-md:col-span-2 max-md:col-start-2 max-md:row-start-2 max-md:empty:hidden"
      :class="projectLayout ? 'self-start pt-0.5 md:justify-end' : ''"
    >
      <PlanSegments v-if="planShown && session.plan" :plan="session.plan" :stopped="planStopped(session)" />
      <span v-if="session.plan_done" data-test="row-plan-done" class="shrink-0 rounded-full border border-primary/40 px-1.5 font-mono text-[0.6875rem] text-primary-soft">Plano concluído</span>
      <ClosureBadge :session="session" />
      <slot name="status">
        <span v-if="reason" data-test="waiting-reason" class="min-w-0 max-w-full truncate text-xs" :class="wantsYou ? 'text-secondary-soft' : 'text-fg-muted'">{{ reason }}</span>
      </slot>
    </div>
    <!-- Kept even when empty, so the columns line up from row to row. The actions float over the right end instead of taking room from them. -->
    <span
      v-if="!projectLayout"
      data-test="row-project"
      class="hidden min-w-0 md:flex"
    ><ProjectTag :project-id="session.project_id" :branch="branchText" /></span>
    <span
      data-test="row-activity"
      class="whitespace-nowrap text-right text-xs text-fg-subtle max-md:col-start-3 max-md:row-start-1"
      :class="projectLayout ? 'pt-0.5' : ''"
    >{{ formatActivity(session.last_activity_at) }}</span>
    <div
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
