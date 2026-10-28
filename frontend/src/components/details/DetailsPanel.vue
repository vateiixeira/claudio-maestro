<script setup lang="ts">
import { computed, defineAsyncComponent, h, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import ContextBreakdown from '../context/ContextBreakdown.vue'
import BranchLabel from '../git/BranchLabel.vue'
import WorktreeLabel from '../git/WorktreeLabel.vue'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import DiffLines from '../conversation/DiffLines.vue'
import GroupProperty from '../groups/GroupProperty.vue'
import LabelProperty from '../labels/LabelProperty.vue'
import PlanProperty from '../plan/PlanProperty.vue'
import PlanStrip from '../plan/PlanStrip.vue'
import { planVisible } from '../plan/planText'
import BranchList from './BranchList.vue'
import ChangesList from './ChangesList.vue'
import DigestSection from './DigestSection.vue'
import FileDiffView from './FileDiffView.vue'
import { useSessionChanges } from '../../conversation/sessionChanges'
import { toolDiff } from '../../conversation/diff'
import { needsYou } from '../../conversation/needsYou'
import { str } from '../../conversation/tool'
import { waitingReason } from '../../conversationList'
import { formatActivity } from '../../format'
import {
  DETAILS_DEFAULT_WIDTH, DETAILS_KEY_STEP, DETAILS_MIN_WIDTH,
  clampDetailsWidth, detailsMaxWidth, readDetailsWidth, writeDetailsWidth,
} from '../../detailsWidthPref'
import type { DetailsTab } from '../../detailsTabPref'
import { displayStateLabel } from '../../sessionState'
import { useChangesPanelStore } from '../../stores/changesPanel'
import { useConversationStore } from '../../stores/conversation'
import { useGitStore } from '../../stores/git'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import { useTerminalStore } from '../../stores/terminal'
import type { ChangedFile, ChangesGroup } from '../../types/api'
import IconBack from '../icons/IconBack.vue'
import IconClose from '../icons/IconClose.vue'
import IconExpand from '../icons/IconExpand.vue'

const props = withDefaults(defineProps<{ sessionId: string; drawer?: boolean; tab?: DetailsTab }>(), { drawer: false, tab: 'details' })
const emit = defineEmits<{ close: []; 'update:tab': [tab: DetailsTab] }>()

// The xterm code is a chunk of its own, downloaded the first time the Terminal tab opens.
const TerminalPane = defineAsyncComponent({
  loader: () => import('../terminal/TerminalPane.vue'),
  loadingComponent: { render: () => h('p', { class: 'm-0 p-4 text-sm text-fg-muted' }, 'Abrindo o terminal…') },
  errorComponent: { render: () => h('p', { role: 'alert', class: 'm-0 p-4 text-sm text-diff-del-fg' }, 'Não foi possível carregar o terminal.') },
  delay: 150,
})

const TABS: Array<{ id: DetailsTab; label: string }> = [
  { id: 'details', label: 'Detalhes' },
  { id: 'terminal', label: 'Terminal' },
]
const current = ref<DetailsTab>(props.tab)
watch(() => props.tab, (tab) => { current.value = tab })
const terminal = useTerminalStore()
function selectTab(tab: DetailsTab) {
  if (current.value === tab) return
  // Choosing the Terminal tab is a gesture: the pane that appears may start the shell.
  if (tab === 'terminal') terminal.requestOpen(props.sessionId)
  current.value = tab
  emit('update:tab', tab)
}
function onTabKey(event: KeyboardEvent, index: number) {
  const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
  if (!step) return
  event.preventDefault()
  const next = TABS[(index + step + TABS.length) % TABS.length]!
  selectTab(next.id)
  const list = (event.currentTarget as HTMLElement | null)?.parentElement
  void nextTick(() => list?.querySelector<HTMLElement>(`[data-test="details-tab-${next.id}"]`)?.focus())
}

const sessions = useSessionsStore()
const conversations = useConversationStore()
const projects = useProjectsStore()
const git = useGitStore()
const panel = useChangesPanelStore()

const session = computed(() => sessions.find(props.sessionId))
const conv = computed(() => conversations.get(props.sessionId))
const projectId = computed(() => session.value?.project_id ?? conv.value?.projectId ?? null)
const project = computed(() => (projectId.value != null ? projects.byId(projectId.value) : undefined))
const repos = computed(() => (projectId.value != null ? git.reposFor(projectId.value) : []))
const context = computed(() => session.value?.context ?? conv.value?.context ?? null)
const turns = computed(() => (conv.value?.items ?? []).filter((i) => i.type === 'user' && !('parent_tool_use_id' in i && i.parent_tool_use_id)).length)
const stateText = computed(() => {
  const s = session.value
  if (!s) return ''
  return waitingReason(s) ?? displayStateLabel(s)
})

const changes = useSessionChanges(() => props.sessionId)

// What the panel shows: properties and the list, or one diff (a file or an edit of the conversation).
const selectedFile = ref<{ group: ChangesGroup; file: ChangedFile } | null>(null)
const editOpen = computed(() => panel.sessionId === props.sessionId && panel.edit != null)
// The diff belongs to the Detalhes tab: on Terminal it stays hidden, and comes back with the tab.
const showingDiff = computed(() => current.value === 'details' && (editOpen.value || selectedFile.value != null))
const wide = ref(false)
const isWide = computed(() => wide.value && showingDiff.value)
const editLines = computed(() => {
  const item = panel.edit
  return item ? toolDiff(item.name, item.input, item.result?.details ?? null) : []
})

function selectFile(group: ChangesGroup, file: ChangedFile) {
  panel.close()
  selectedFile.value = { group, file }
}
function back() {
  selectedFile.value = null
  if (editOpen.value) panel.close()
  wide.value = false
}
watch(() => props.sessionId, back)
// An edit opened from the conversation replaces a selected file.
watch(editOpen, (open) => {
  if (!open) return
  selectedFile.value = null
  // Only what is shown now changes: the tab the user chose to open the panel on is not touched.
  current.value = 'details'
})

const viewport = ref(window.innerWidth)
const onWindowResize = () => { viewport.value = window.innerWidth }
onMounted(() => window.addEventListener('resize', onWindowResize))
onBeforeUnmount(() => window.removeEventListener('resize', onWindowResize))

const width = ref(readDetailsWidth())
const applied = computed(() => clampDetailsWidth(width.value, viewport.value, props.drawer))
const maxWidth = computed(() => detailsMaxWidth(viewport.value, props.drawer))

// The handle sits on the left edge: moving the pointer left makes the panel wider.
let drag: { startX: number; startWidth: number } | null = null
function startDrag(event: PointerEvent) {
  event.preventDefault()
  ;(event.currentTarget as HTMLElement | null)?.setPointerCapture?.(event.pointerId)
  drag = { startX: event.clientX, startWidth: applied.value }
}
function moveDrag(event: PointerEvent) {
  if (!drag) return
  width.value = clampDetailsWidth(drag.startWidth + (drag.startX - event.clientX), viewport.value, props.drawer)
}
function endDrag() {
  if (!drag) return
  drag = null
  writeDetailsWidth(applied.value)
}
function onResizeKey(event: KeyboardEvent) {
  const delta = event.key === 'ArrowLeft' ? DETAILS_KEY_STEP : event.key === 'ArrowRight' ? -DETAILS_KEY_STEP : 0
  if (!delta) return
  event.preventDefault()
  width.value = clampDetailsWidth(applied.value + delta, viewport.value, props.drawer)
  writeDetailsWidth(width.value)
}
function resetWidth() {
  width.value = DETAILS_DEFAULT_WIDTH
  writeDetailsWidth(width.value)
}
</script>

<template>
  <aside
    data-test="details-panel"
    :data-wide="String(isWide)"
    aria-label="Detalhes da conversa"
    class="relative flex h-full shrink-0 flex-col border-l border-line-strong bg-bg"
    :class="[isWide ? 'w-[60vw]' : '', drawer ? 'max-w-full' : '']"
    :style="isWide ? undefined : { width: `${applied}px` }"
  >
    <div
      v-if="!isWide"
      data-test="details-resize"
      role="separator"
      aria-orientation="vertical"
      aria-label="Redimensionar detalhes"
      tabindex="0"
      :aria-valuenow="applied"
      :aria-valuemin="DETAILS_MIN_WIDTH"
      :aria-valuemax="maxWidth"
      title="Arraste para redimensionar · duplo clique volta ao padrão"
      class="absolute inset-y-0 -left-1 z-10 w-2 cursor-col-resize touch-none hover:bg-line-strong focus-visible:bg-fg-muted/40 focus-visible:outline-none"
      @pointerdown="startDrag"
      @pointermove="moveDrag"
      @pointerup="endDrag"
      @pointercancel="endDrag"
      @dblclick="resetWidth"
      @keydown="onResizeKey"
    />
    <header class="flex min-h-12 items-center gap-2 border-b border-line px-4">
      <template v-if="showingDiff">
        <button
          type="button"
          data-test="diff-back"
          class="flex h-8 items-center gap-1 rounded-md pr-2 pl-1 text-sm text-fg-muted hover:bg-card hover:text-fg"
          @click="back"
        ><IconBack :size="14" />Voltar</button>
        <span class="grow" />
        <button
          type="button"
          data-test="diff-expand"
          :aria-label="wide ? 'Voltar à largura normal' : 'Alargar o painel'"
          :aria-pressed="wide"
          class="flex size-8 items-center justify-center rounded-md text-fg-muted hover:bg-card hover:text-fg"
          @click="wide = !wide"
        ><IconExpand :size="14" /></button>
      </template>
      <div v-else role="tablist" aria-label="Painel da conversa" class="flex grow items-center gap-1">
        <button
          v-for="(item, index) in TABS"
          :id="`details-tab-${item.id}`"
          :key="item.id"
          type="button"
          role="tab"
          :data-test="`details-tab-${item.id}`"
          :aria-selected="current === item.id"
          aria-controls="details-tabpanel"
          :tabindex="current === item.id ? 0 : -1"
          class="h-8 rounded-md px-2.5 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-primary"
          :class="current === item.id ? 'text-fg' : 'font-medium text-fg-muted hover:bg-card hover:text-fg'"
          @click="selectTab(item.id)"
          @keydown="onTabKey($event, index)"
        >{{ item.label }}</button>
      </div>
      <button
        v-if="drawer"
        type="button"
        aria-label="Fechar detalhes"
        class="flex size-8 items-center justify-center rounded-md text-fg-muted hover:bg-card hover:text-fg"
        @click="emit('close')"
      ><IconClose :size="14" /></button>
    </header>

    <div
      v-if="current === 'terminal'"
      id="details-tabpanel"
      data-test="details-body"
      role="tabpanel"
      aria-labelledby="details-tab-terminal"
      class="relative flex min-h-0 grow flex-col overflow-hidden"
    >
      <TerminalPane :key="sessionId" :session-id="sessionId" />
    </div>
    <div
      v-else
      id="details-tabpanel"
      data-test="details-body"
      role="tabpanel"
      aria-labelledby="details-tab-details"
      class="relative flex min-h-0 grow flex-col gap-5 overflow-y-auto p-4"
    >
      <template v-if="showingDiff">
        <section v-if="editOpen && panel.edit" data-test="details-diff" class="overflow-hidden rounded-lg border border-line bg-panel">
          <div class="truncate border-b border-line px-3 py-2 font-mono text-xs text-fg-muted">{{ str(panel.edit.input.file_path) }}</div>
          <DiffLines :lines="editLines" />
        </section>
        <section v-else-if="selectedFile && projectId != null" data-test="details-diff">
          <FileDiffView :project-id="projectId" :group="selectedFile.group" :file="selectedFile.file" />
        </section>
      </template>
      <template v-else>
        <section data-test="details-properties" aria-labelledby="props-title" class="flex flex-col gap-2.5">
          <h3 id="props-title" class="m-0 font-mono text-[0.65625rem] font-semibold tracking-[0.08em] text-fg-subtle uppercase">Propriedades</h3>
          <div class="overflow-hidden rounded-lg border border-line bg-panel">
            <dl data-test="props-session" class="m-0 grid grid-cols-[7.2rem_1fr] gap-x-3 gap-y-2 px-3 py-2.5 text-[0.8125rem]">
              <dt class="text-fg-muted">Estado</dt>
              <dd data-test="prop-state" class="m-0 flex items-center gap-1.5" :class="session?.display_state === 'waiting' ? (needsYou(session) ? 'font-medium text-secondary-soft' : 'text-fg-muted') : ''">
                <DisplayStateIcon v-if="session" :display="session.display_state" :quiet="!needsYou(session)" />{{ stateText }}
              </dd>
              <dt class="text-fg-muted">Turnos</dt>
              <dd data-test="prop-turns" class="m-0">{{ turns }}</dd>
              <dt class="text-fg-muted">Início</dt>
              <dd data-test="prop-created" class="m-0">{{ session ? formatActivity(session.created_at) : '' }}</dd>
              <dt class="text-fg-muted">Última atividade</dt>
              <dd data-test="prop-activity" class="m-0">{{ session ? formatActivity(session.last_activity_at) : '' }}</dd>
            </dl>
            <dl data-test="props-environment" class="m-0 grid grid-cols-[7.2rem_1fr] gap-x-3 gap-y-2 border-t border-line px-3 py-2.5 text-[0.8125rem]">
              <dt class="text-fg-muted">Projeto</dt>
              <dd data-test="prop-project" class="m-0 min-w-0">
                <RouterLink v-if="project" :to="{ name: 'project', params: { id: project.id } }" class="flex items-center gap-1.5 text-fg no-underline hover:text-fg hover:underline">
                  <span class="size-2 shrink-0 rounded-[3px]" :style="{ backgroundColor: project.color }" />
                  <span class="truncate">{{ project.name }}</span>
                </RouterLink>
              </dd>
              <dt class="text-fg-muted">Branch</dt>
              <dd data-test="prop-branch" class="m-0 flex min-w-0 flex-col gap-1">
                <template v-if="session?.worktree_name">
                  <BranchLabel v-if="session.git_branch" :text="session.git_branch" />
                  <span v-else class="text-fg-muted">desconhecido</span>
                </template>
                <template v-else>
                  <BranchList v-if="projectId != null && repos.length > 0" :key="sessionId" :project-id="projectId" :repos="repos" />
                  <span v-if="repos.length === 0" class="text-fg-muted">sem repositório git</span>
                </template>
              </dd>
              <template v-if="session?.worktree_name">
                <dt class="text-fg-muted">Worktree</dt>
                <dd data-test="prop-worktree" class="m-0 min-w-0">
                  <span :title="session.worktree_path ?? undefined"><WorktreeLabel :text="session.worktree_name" /></span>
                </dd>
              </template>
              <!-- The breakdown needs the whole width: label and content each take a full row of the grid. -->
              <dt class="col-span-2 text-fg-muted">Contexto</dt>
              <dd data-test="prop-context" class="col-span-2 -mt-1 min-w-0">
                <ContextBreakdown v-if="context" :session-id="sessionId" :context="context" variant="panel" />
                <span v-else class="text-fg-muted">Desconhecido</span>
              </dd>
              <GroupProperty v-if="projectId != null" :session-id="sessionId" :project-id="projectId" />
              <LabelProperty v-if="session" :session-id="sessionId" />
            </dl>
          </div>
        </section>
        <section v-if="session && projectId != null" data-test="details-plan" aria-labelledby="plan-title" class="flex flex-col gap-2">
          <h3 id="plan-title" class="m-0 font-mono text-[0.65625rem] font-semibold tracking-[0.08em] text-fg-subtle uppercase">Plano</h3>
          <PlanStrip v-if="planVisible(session)" :key="sessionId" :session="session" variant="panel">
            <template #actions><PlanProperty :session-id="sessionId" :project-id="projectId" :summary="false" /></template>
          </PlanStrip>
          <PlanProperty v-else :session-id="sessionId" :project-id="projectId" />
        </section>
        <DigestSection :session-id="sessionId" />
        <section data-test="details-changes" aria-labelledby="changes-title" class="flex flex-col gap-2">
          <h3 id="changes-title" class="m-0 flex items-center gap-2 font-mono text-[0.65625rem] font-semibold tracking-[0.08em] text-fg-subtle uppercase">
            Alterações
            <span class="ml-auto text-[0.71875rem] font-normal normal-case tracking-normal"><span class="text-diff-add-fg">+{{ changes.total.value.added }}</span> <span class="text-diff-del-fg">−{{ changes.total.value.removed }}</span></span>
          </h3>
          <ChangesList
            :groups="changes.groups.value"
            :loading="changes.loading.value"
            :error="changes.error.value"
            :selected="null"
            @select="selectFile"
            @retry="changes.reload()"
          />
        </section>
      </template>
    </div>
  </aside>
</template>
