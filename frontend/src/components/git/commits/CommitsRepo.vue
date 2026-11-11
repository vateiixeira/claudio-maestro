<script lang="ts">
// Keep observed revisions across panel remounts, scoped to the Pinia store lifetime.
const observedRevisions = new WeakMap<object, Map<string, number>>()
</script>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import CommitRow from './CommitRow.vue'
import HistoryRefMenu from './HistoryRefMenu.vue'
import BranchComparison from './BranchComparison.vue'
import RepoName from '../RepoName.vue'
import RepoStateBadges from '../RepoStateBadges.vue'
import IconChevron from '../../icons/IconChevron.vue'
import { useRepoExpansion } from '../../../git/repoExpansion'
import { repoLabel, syncCounts } from '../../../git/repoLabel'
import { formatActivity } from '../../../format'
import { useGitDetailsStore } from '../../../stores/gitDetails'
import { useGitLogStore } from '../../../stores/gitLog'
import { useProjectsStore } from '../../../stores/projects'
import type { RepoDetails } from '../../../types/api'

const props = withDefaults(defineProps<{ projectId: number; repo: RepoDetails; collapseAll: number; startOpen?: boolean; forceOpen?: boolean; active?: boolean }>(), { active: true })

const details = useGitDetailsStore()
const log = useGitLogStore()
const projects = useProjectsStore()
const open = useRepoExpansion(() => props.projectId, () => props.repo.path, 'commits', () => props.startOpen ?? false)
watch(() => props.forceOpen, (value) => { if (value) open.value = true }, { immediate: true })
const menuOpen = ref(false)
const showOutgoing = ref(false)
const showIncoming = ref(false)

const state = computed(() => log.logFor(props.projectId, props.repo.path))
const name = computed(() => repoLabel(props.repo, projects.byId(props.projectId)?.name))
const sync = computed(() => syncCounts(state.value && (state.value.headSha !== null || state.value.incomingCount !== null) ? { upstream: state.value.upstream, ahead: state.value.outgoingCount, behind: state.value.incomingCount } : props.repo))
const outgoingState = computed(() => log.logFor(props.projectId, props.repo.path, 'outgoing'))
const incomingState = computed(() => log.logFor(props.projectId, props.repo.path, 'incoming'))
const remoteName = computed(() => state.value?.upstream?.split('/')[0] ?? null)
const fetched = computed(() => (props.repo.fetched_at ? `buscado ${formatActivity(props.repo.fetched_at)}` : null))

const plural = (n: number) => (n === 1 ? '1 commit' : `${n} commits`)
const outgoingLabel = computed(() => `Para subir — ${state.value?.outgoingCount ? plural(state.value.outgoingCount) : 'nenhum'}`)
const incomingLabel = computed(() => `Para baixar — ${state.value?.incomingCount ? plural(state.value.incomingCount) : 'nenhum'}`)

function toggle(): void {
  open.value = !open.value
}

const revisionKey = computed(() => JSON.stringify([props.projectId, props.repo.path]))
let revisions = observedRevisions.get(log)
if (!revisions) {
  revisions = new Map()
  observedRevisions.set(log, revisions)
}
function ensureHistory(force = false): void {
  const revision = details.historyRevisionFor(props.projectId, props.repo.path)
  if (!state.value) void log.load(props.projectId, props.repo.path)
  else if (force || state.value.error || revisions!.get(revisionKey.value) !== revision) void log.refresh(props.projectId, props.repo.path)
  revisions!.set(revisionKey.value, revision)
}
watch([open, () => props.active], ([value, active]) => { if (value && active !== false) ensureHistory() }, { immediate: true })
watch(() => props.collapseAll, () => { open.value = false; menuOpen.value = false })
watch(() => details.historyRevisionFor(props.projectId, props.repo.path), () => {
  if (open.value && props.active !== false) ensureHistory()
})

// Reopen cached directions without another request; a new snapshot clears their caches.
watch(() => [state.value?.loading, state.value?.headSha, showOutgoing.value, showIncoming.value, props.active], () => {
  if (props.active === false || !open.value || !state.value || state.value.loading) return
  if (showOutgoing.value && !outgoingState.value) void log.loadDirection(props.projectId, props.repo.path, 'outgoing')
  if (showIncoming.value && !incomingState.value) void log.loadDirection(props.projectId, props.repo.path, 'incoming')
})

function pick(refName: string): void {
  menuOpen.value = false
  void log.setRef(props.projectId, props.repo.path, refName)
}
</script>

<template>
  <li data-test="commits-repo" :data-repo="repo.path" class="flex min-w-0 flex-col rounded-md border border-line odd:bg-panel even:bg-card/40">
    <div class="relative flex min-h-10 min-w-0 flex-wrap items-center gap-x-2 gap-y-1 rounded-t-md px-2 py-1.5" :class="open ? 'border-b border-line bg-elevated/60' : 'hover:bg-elevated/60'">
      <button type="button" data-test="commits-repo-toggle" :title="name" :aria-expanded="open" class="flex min-w-0 flex-[1_1_9rem] items-center gap-1.5 py-0.5 text-left sm:max-w-[35%] sm:flex-none" @click="toggle">
        <IconChevron :open="open" :size="12" class="text-fg-subtle" />
        <RepoName :name="name" />
      </button>
      <button
        type="button"
        data-test="history-ref"
        aria-haspopup="listbox"
        :aria-expanded="menuOpen"
        title="Escolher a branch do histórico (não troca de branch)"
        class="h-6 max-w-[45%] shrink truncate rounded border border-line bg-panel px-1.5 font-mono text-xs text-fg-muted hover:bg-card hover:text-fg sm:max-w-56"
        @click="menuOpen = !menuOpen"
      >{{ state?.branch ?? repo.branch ?? repo.head ?? '' }}</button>
      <RepoStateBadges :sync="sync" :error="!!state?.error" />
      <span v-if="fetched" data-test="fetched-ago" class="max-w-[25%] truncate text-xs text-fg-subtle" :title="fetched">{{ fetched }}</span>
      <HistoryRefMenu
        v-if="menuOpen"
        :project-id="projectId"
        :repo-path="repo.path"
        :current="state?.ref ?? null"
        @select="pick"
        @close="menuOpen = false"
      />
    </div>

    <div v-if="open" class="flex min-w-0 flex-col px-3 py-2.5">
      <p v-if="state?.error" role="alert" class="m-0 py-1 text-xs text-diff-del-fg">{{ state.error }} <button type="button" data-test="history-retry" class="underline" :disabled="state.loading" @click="ensureHistory(true)">Tentar novamente</button></p>
      <p v-if="!state || (state.loading && state.commits.length === 0)" class="m-0 py-1 text-xs text-fg-muted">Carregando…</p>
      <template v-else>
        <button v-if="state.updateAvailable" type="button" data-test="apply-history-update" :disabled="state.loading" class="self-start rounded px-1.5 py-1 text-xs text-info-soft hover:bg-elevated" @click="log.load(projectId, repo.path)">Há alterações no histórico. Atualizar</button>
        <div data-test="group-outgoing">
          <button type="button" :aria-expanded="showOutgoing" class="flex h-6 w-full items-center gap-1.5 text-left text-xs text-fg-muted hover:text-fg" :disabled="!state.outgoingCount" @click="showOutgoing = !showOutgoing">
            <IconChevron :open="showOutgoing" :size="12" class="text-fg-subtle" />{{ outgoingLabel }}
          </button>
          <div v-if="showOutgoing" class="pl-4">
            <p v-if="outgoingState?.error" role="alert" class="m-0 py-1 text-xs text-diff-del-fg">{{ outgoingState.error }} <button type="button" class="underline" @click="log.loadDirection(projectId, repo.path, 'outgoing')">Tentar novamente</button></p>
            <p v-if="!outgoingState || (outgoingState.loading && !outgoingState.commits.length)" class="m-0 py-1 text-xs text-fg-muted">Carregando…</p>
            <ul data-test="outgoing-list" class="m-0 list-none p-0">
            <CommitRow v-for="c in outgoingState?.commits ?? []" :key="c.full_hash" :project-id="projectId" :repo-path="repo.path" :commit="c" :upstream-label="null" :user-email="repo.state?.user_email ?? null" />
            </ul>
            <button v-if="outgoingState?.hasMore" type="button" data-test="load-more-outgoing" :disabled="outgoingState.loading" class="h-6 rounded px-1.5 text-xs text-fg-muted hover:bg-elevated" @click="log.loadMore(projectId, repo.path, 'outgoing')">{{ outgoingState.loading ? 'Carregando…' : 'Carregar mais para subir' }}</button>
          </div>
        </div>
        <div data-test="group-incoming">
          <button type="button" :aria-expanded="showIncoming" class="flex h-6 w-full items-center gap-1.5 text-left text-xs text-fg-muted hover:text-fg" :disabled="!state.incomingCount" @click="showIncoming = !showIncoming">
            <IconChevron :open="showIncoming" :size="12" class="text-fg-subtle" />{{ incomingLabel }}
          </button>
          <div v-if="showIncoming" class="pl-4">
            <p v-if="incomingState?.error" role="alert" class="m-0 py-1 text-xs text-diff-del-fg">{{ incomingState.error }} <button type="button" class="underline" @click="log.loadDirection(projectId, repo.path, 'incoming')">Tentar novamente</button></p>
            <p v-if="!incomingState || (incomingState.loading && !incomingState.commits.length)" class="m-0 py-1 text-xs text-fg-muted">Carregando…</p>
            <ul data-test="incoming-list" class="m-0 list-none p-0">
            <CommitRow v-for="c in incomingState?.commits ?? []" :key="c.full_hash" :project-id="projectId" :repo-path="repo.path" :commit="c" :upstream-label="c.full_hash === state.upstreamSha ? remoteName : null" :user-email="repo.state?.user_email ?? null" />
            </ul>
            <button v-if="incomingState?.hasMore" type="button" data-test="load-more-incoming" :disabled="incomingState.loading" class="h-6 rounded px-1.5 text-xs text-fg-muted hover:bg-elevated" @click="log.loadMore(projectId, repo.path, 'incoming')">{{ incomingState.loading ? 'Carregando…' : 'Carregar mais para baixar' }}</button>
          </div>
        </div>
        <BranchComparison
          :active="active"
          :project-id="projectId" :repo-path="repo.path" :head-ref="state.ref"
          :branch="(state.ref ? state.branch : repo.branch) ?? 'HEAD'"
          :revision="details.historyRevisionFor(projectId, repo.path)"
          :default-base="repo.upstream ? `refs/remotes/${repo.upstream}` : null"
          :user-email="repo.state?.user_email ?? null"
        />
        <ul class="m-0 list-none p-0">
          <CommitRow
            v-for="c in state.commits"
            :key="c.full_hash"
            :project-id="projectId"
            :repo-path="repo.path"
            :commit="c"
            :upstream-label="c.full_hash === state.upstreamSha ? remoteName : null"
            :user-email="repo.state?.user_email ?? null"
          />
        </ul>
        <p v-if="state.commits.length === 0 && !state.error" class="m-0 py-1 text-xs text-fg-muted">Ainda não há commits.</p>
        <button v-if="state.hasMore" type="button" data-test="load-more" :disabled="state.loading" class="h-6 self-start rounded px-1.5 text-xs text-fg-muted hover:bg-elevated hover:text-fg" @click="log.loadMore(projectId, repo.path)">{{ state.loading ? 'Carregando…' : 'Carregar mais' }}</button>
      </template>
    </div>
  </li>
</template>
