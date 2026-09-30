<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import BranchLabel from '../git/BranchLabel.vue'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import DiffLines from '../conversation/DiffLines.vue'
import PlanProperty from '../plan/PlanProperty.vue'
import ChangesList from './ChangesList.vue'
import FileDiffView from './FileDiffView.vue'
import { useSessionChanges } from '../../conversation/sessionChanges'
import { toolDiff } from '../../conversation/diff'
import { str } from '../../conversation/tool'
import { waitingReason } from '../../conversationList'
import { formatActivity, formatTokens } from '../../format'
import { displayStateLabels } from '../../sessionState'
import { useChangesPanelStore } from '../../stores/changesPanel'
import { useConversationStore } from '../../stores/conversation'
import { repoLabel, useGitStore } from '../../stores/git'
import { useProjectsStore } from '../../stores/projects'
import { useSessionsStore } from '../../stores/sessions'
import type { ChangedFile, ChangesGroup } from '../../types/api'

const props = withDefaults(defineProps<{ sessionId: string; drawer?: boolean }>(), { drawer: false })
const emit = defineEmits<{ close: [] }>()

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
  return waitingReason(s) ?? displayStateLabels[s.display_state]
})

const changes = useSessionChanges(() => props.sessionId)

// What the panel shows: properties and the list, or one diff (a file or an edit of the conversation).
const selectedFile = ref<{ group: ChangesGroup; file: ChangedFile } | null>(null)
const editOpen = computed(() => panel.sessionId === props.sessionId && panel.edit != null)
const showingDiff = computed(() => editOpen.value || selectedFile.value != null)
const wide = ref(false)
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
watch(editOpen, (open) => { if (open) selectedFile.value = null })
</script>

<template>
  <aside
    data-test="details-panel"
    :data-wide="String(wide)"
    aria-label="Detalhes da conversa"
    class="flex h-full shrink-0 flex-col border-l border-line bg-panel"
    :class="[wide ? 'w-[60vw]' : 'w-[360px]', drawer ? 'max-w-full' : '']"
  >
    <header class="flex min-h-12 items-center gap-2 border-b border-line px-4">
      <template v-if="showingDiff">
        <button
          type="button"
          data-test="diff-back"
          class="h-8 rounded-md px-2 text-sm text-fg-muted hover:bg-card hover:text-fg"
          @click="back"
        >‹ Voltar</button>
        <span class="grow" />
        <button
          type="button"
          data-test="diff-expand"
          :aria-label="wide ? 'Voltar à largura normal' : 'Alargar o painel'"
          :aria-pressed="wide"
          class="flex size-8 items-center justify-center rounded-md text-fg-muted hover:bg-card hover:text-fg"
          @click="wide = !wide"
        >⤢</button>
      </template>
      <h2 v-else class="m-0 grow text-sm font-semibold">Detalhes</h2>
      <button
        v-if="drawer"
        type="button"
        aria-label="Fechar detalhes"
        class="flex size-8 items-center justify-center rounded-md text-fg-muted hover:bg-card hover:text-fg"
        @click="emit('close')"
      >×</button>
    </header>

    <div class="flex min-h-0 grow flex-col gap-5 overflow-y-auto p-4">
      <template v-if="showingDiff">
        <section v-if="editOpen && panel.edit" data-test="details-diff" class="overflow-hidden rounded-lg border border-line bg-bg">
          <div class="truncate border-b border-line px-3 py-2 font-mono text-xs text-fg-muted">{{ str(panel.edit.input.file_path) }}</div>
          <DiffLines :lines="editLines" />
        </section>
        <section v-else-if="selectedFile && projectId != null" data-test="details-diff">
          <FileDiffView :project-id="projectId" :group="selectedFile.group" :file="selectedFile.file" />
        </section>
      </template>
      <template v-else>
        <section data-test="details-properties" aria-labelledby="props-title" class="flex flex-col gap-2">
          <h3 id="props-title" class="m-0 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Propriedades</h3>
          <dl class="m-0 grid grid-cols-[7rem_1fr] gap-x-3 gap-y-2 text-sm">
            <dt class="text-fg-muted">Estado</dt>
            <dd data-test="prop-state" class="m-0 flex items-center gap-1.5">
              <DisplayStateIcon v-if="session" :display="session.display_state" />{{ stateText }}
            </dd>
            <dt class="text-fg-muted">Projeto</dt>
            <dd data-test="prop-project" class="m-0 min-w-0">
              <RouterLink v-if="project" :to="{ name: 'project', params: { id: project.id } }" class="flex items-center gap-1.5 text-fg no-underline hover:text-primary-soft">
                <span class="size-2 shrink-0 rounded-[3px]" :style="{ backgroundColor: project.color }" />
                <span class="truncate">{{ project.name }}</span>
              </RouterLink>
            </dd>
            <dt class="text-fg-muted">Branch</dt>
            <dd data-test="prop-branch" class="m-0 flex min-w-0 flex-col gap-1">
              <BranchLabel v-for="repo in repos" :key="repo.path" :text="repoLabel(repo)" :muted="!!repo.error" />
              <span v-if="repos.length === 0" class="text-fg-muted">sem repositório git</span>
            </dd>
            <dt class="text-fg-muted">Contexto</dt>
            <dd data-test="prop-context" class="m-0 flex flex-col gap-1">
              <template v-if="context">
                <span :class="context.percent >= 80 ? 'text-secondary' : 'text-fg'">{{ Math.round(context.percent) }}% · {{ formatTokens(context.used_tokens) }} de {{ formatTokens(context.max_tokens) }}</span>
                <span class="h-1.5 overflow-hidden rounded-full bg-line" aria-hidden="true">
                  <span class="block h-full rounded-full" :class="context.percent >= 80 ? 'bg-secondary' : 'bg-primary'" :style="{ width: `${Math.min(context.percent, 100)}%` }" />
                </span>
              </template>
              <span v-else class="text-fg-muted">Desconhecido</span>
            </dd>
            <dt class="text-fg-muted">Turnos</dt>
            <dd data-test="prop-turns" class="m-0">{{ turns }}</dd>
            <dt class="text-fg-muted">Início</dt>
            <dd data-test="prop-created" class="m-0">{{ session ? formatActivity(session.created_at) : '' }}</dd>
            <dt class="text-fg-muted">Última atividade</dt>
            <dd data-test="prop-activity" class="m-0">{{ session ? formatActivity(session.last_activity_at) : '' }}</dd>
            <PlanProperty v-if="projectId != null" :session-id="sessionId" :project-id="projectId" />
          </dl>
        </section>
        <section data-test="details-changes" aria-labelledby="changes-title" class="flex flex-col gap-2">
          <h3 id="changes-title" class="m-0 flex items-center gap-2 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">
            Alterações
            <span class="normal-case tracking-normal"><span class="text-diff-add-fg">+{{ changes.total.value.added }}</span> <span class="text-diff-del-fg">−{{ changes.total.value.removed }}</span></span>
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
