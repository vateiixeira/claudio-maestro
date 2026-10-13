<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import CommitRow from './CommitRow.vue'
import HistoryRefMenu from './HistoryRefMenu.vue'
import IconArrowDown from '../../icons/IconArrowDown.vue'
import IconArrowUp from '../../icons/IconArrowUp.vue'
import IconChevron from '../../icons/IconChevron.vue'
import { repoLabel, syncCounts } from '../../../git/repoLabel'
import { formatActivity } from '../../../format'
import { useGitDetailsStore } from '../../../stores/gitDetails'
import { useGitLogStore } from '../../../stores/gitLog'
import { useProjectsStore } from '../../../stores/projects'
import type { RepoDetails } from '../../../types/api'

const props = defineProps<{ projectId: number; repo: RepoDetails; collapseAll: number }>()

const details = useGitDetailsStore()
const log = useGitLogStore()
const projects = useProjectsStore()
const open = ref(false)
const menuOpen = ref(false)
const showOutgoing = ref(false)
const showIncoming = ref(false)

const state = computed(() => log.logFor(props.projectId, props.repo.path))
const name = computed(() => repoLabel(props.repo, projects.byId(props.projectId)?.name))
const sync = computed(() => syncCounts(props.repo))
const outgoing = computed(() => (state.value?.commits ?? []).filter((c) => c.pushed === false))
const remoteName = computed(() => state.value?.upstream?.split('/')[0] ?? null)
const fetched = computed(() => (props.repo.fetched_at ? `buscado ${formatActivity(props.repo.fetched_at)}` : null))

const plural = (n: number) => (n === 1 ? '1 commit' : `${n} commits`)
const outgoingLabel = computed(() => `Para subir — ${state.value?.outgoingCount ? plural(state.value.outgoingCount) : 'nenhum'}`)
const incomingLabel = computed(() => `Para baixar — ${state.value?.incomingCount ? plural(state.value.incomingCount) : 'nenhum'}`)

function toggle(): void {
  open.value = !open.value
  if (!open.value) return
  // Reopening shows what was loaded before, which may be old: git changed while it was closed.
  if (state.value) void log.refresh(props.projectId, props.repo.path)
  else void log.load(props.projectId, props.repo.path)
}

watch(() => props.collapseAll, () => { open.value = false; menuOpen.value = false })
// The details were reread (a commit, a fetch, a turn that ended): reread the history shown.
watch(() => details.revisionFor(props.projectId), () => {
  if (open.value && state.value) void log.refresh(props.projectId, props.repo.path)
})

function pick(refName: string): void {
  menuOpen.value = false
  void log.setRef(props.projectId, props.repo.path, refName)
}
</script>

<template>
  <li data-test="commits-repo" class="flex flex-col">
    <div class="relative flex h-7 items-center gap-1.5 rounded px-1 hover:bg-elevated">
      <button type="button" data-test="commits-repo-toggle" :aria-expanded="open" class="flex min-w-0 grow items-center gap-1.5 text-left" @click="toggle">
        <IconChevron :open="open" :size="12" class="text-fg-subtle" />
        <span class="truncate font-mono text-[0.8125rem] font-semibold text-fg">{{ name }}</span>
      </button>
      <button
        type="button"
        data-test="history-ref"
        aria-haspopup="listbox"
        :aria-expanded="menuOpen"
        title="Escolher a branch do histórico (não troca de branch)"
        class="h-6 max-w-48 truncate rounded px-1.5 font-mono text-xs text-fg-muted hover:bg-card hover:text-fg"
        @click="menuOpen = !menuOpen"
      >{{ state?.branch ?? repo.branch ?? repo.head ?? '' }}</button>
      <span
        data-test="sync-counts"
        class="inline-flex shrink-0 items-center gap-1.5 font-mono text-xs"
        :role="sync.kind === 'diverged' ? 'img' : undefined"
        :aria-label="sync.kind === 'diverged' ? `${sync.behind} para baixar, ${sync.ahead} para subir` : undefined"
      >
        <span v-if="sync.kind === 'none'" class="text-fg-subtle">sem upstream</span>
        <span v-else-if="sync.kind === 'synced'" class="text-fg-subtle">em dia</span>
        <template v-else-if="sync.kind === 'diverged'">
          <span class="inline-flex items-center" :class="sync.behind > 0 ? 'text-info-soft' : 'text-fg-subtle'"><IconArrowDown :size="12" />{{ sync.behind }}</span>
          <span class="inline-flex items-center" :class="sync.ahead > 0 ? 'text-fg' : 'text-fg-subtle'"><IconArrowUp :size="12" />{{ sync.ahead }}</span>
        </template>
      </span>
      <span v-if="fetched" data-test="fetched-ago" class="shrink-0 text-xs text-fg-subtle">{{ fetched }}</span>
      <HistoryRefMenu
        v-if="menuOpen"
        :project-id="projectId"
        :repo-path="repo.path"
        :current="state?.ref ?? null"
        @select="pick"
        @close="menuOpen = false"
      />
    </div>

    <div v-if="open" class="flex flex-col pl-5">
      <p v-if="state?.error" role="alert" class="m-0 py-1 text-xs text-diff-del-fg">{{ state.error }}</p>
      <p v-else-if="!state || (state.loading && state.commits.length === 0)" class="m-0 py-1 text-xs text-fg-muted">Carregando…</p>
      <template v-else>
        <div data-test="group-outgoing">
          <button type="button" :aria-expanded="showOutgoing" class="flex h-6 w-full items-center gap-1.5 text-left text-xs text-fg-muted hover:text-fg" :disabled="!state.outgoingCount" @click="showOutgoing = !showOutgoing">
            <IconChevron :open="showOutgoing" :size="12" class="text-fg-subtle" />{{ outgoingLabel }}
          </button>
          <ul v-if="showOutgoing" class="m-0 list-none p-0 pl-4">
            <CommitRow v-for="c in outgoing" :key="c.full_hash" :project-id="projectId" :repo-path="repo.path" :commit="c" :upstream-label="null" :user-email="repo.state?.user_email ?? null" />
          </ul>
        </div>
        <div data-test="group-incoming">
          <button type="button" :aria-expanded="showIncoming" class="flex h-6 w-full items-center gap-1.5 text-left text-xs text-fg-muted hover:text-fg" :disabled="!state.incomingCount" @click="showIncoming = !showIncoming">
            <IconChevron :open="showIncoming" :size="12" class="text-fg-subtle" />{{ incomingLabel }}
          </button>
          <ul v-if="showIncoming" data-test="incoming-list" class="m-0 list-none p-0 pl-4">
            <CommitRow v-for="c in state.incoming" :key="c.full_hash" :project-id="projectId" :repo-path="repo.path" :commit="c" :upstream-label="c.full_hash === state.upstreamSha ? remoteName : null" :user-email="repo.state?.user_email ?? null" />
          </ul>
        </div>
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
        <p v-if="state.commits.length === 0" class="m-0 py-1 text-xs text-fg-muted">Ainda não há commits.</p>
        <button v-if="state.hasMore" type="button" data-test="load-more" :disabled="state.loading" class="h-6 self-start rounded px-1.5 text-xs text-fg-muted hover:bg-elevated hover:text-fg" @click="log.loadMore(projectId, repo.path)">{{ state.loading ? 'Carregando…' : 'Carregar mais' }}</button>
      </template>
    </div>
  </li>
</template>
