<script setup lang="ts">
import { computed } from 'vue'
import IconArrowDown from '../icons/IconArrowDown.vue'
import IconArrowUp from '../icons/IconArrowUp.vue'
import { checkedAgoText, commitsText, lastSuccessText, syncState } from '../../gitSync'
import { useMinuteClock } from '../../minuteClock'
import { useGitStore } from '../../stores/git'
import type { GitRepo } from '../../types/api'

// How the branch stands against its remote (Detalhes, under the branch name) and the "Verificar agora" button.
const props = defineProps<{ projectId: number; repo: GitRepo }>()

const git = useGitStore()
const now = useMinuteClock()

const state = computed(() => syncState(props.repo))
const failed = computed(() => !!props.repo.fetch_error)
const busy = computed(() => git.isFetching(props.projectId))
const requestError = computed(() => git.fetchError(props.projectId))
// "verificado há 2 min", "não consegui verificar · última vez há 40 min", or nothing before the first check.
const status = computed(() => {
  if (failed.value) return ['não consegui verificar', lastSuccessText(props.repo, now.value)].filter(Boolean).join(' · ')
  const ago = checkedAgoText(props.repo, now.value)
  return ago ? `verificado ${ago}` : ''
})
</script>

<template>
  <div data-test="prop-branch-sync" class="flex min-w-0 flex-col gap-0.5 text-xs text-fg-subtle">
    <template v-if="state.kind === 'no-upstream'">sem branch remota</template>
    <template v-else-if="state.kind === 'fetching'">verificando…</template>
    <template v-else>
      <span
        data-test="prop-branch-sync-line"
        class="min-w-0"
        :class="state.kind === 'behind' || state.kind === 'diverged' ? 'text-secondary-soft' : 'text-fg-subtle'"
      >
        <template v-if="state.kind === 'diverged'">
          <span class="inline-flex items-center gap-1 align-middle"><IconArrowDown :size="11" class="shrink-0" />{{ state.behind }} para baixar</span> · <span class="inline-flex items-center gap-1 align-middle"><IconArrowUp :size="11" class="shrink-0" />{{ state.ahead }} para subir</span> · <span class="font-mono">{{ state.upstream }}</span>
        </template>
        <span v-else-if="state.kind === 'behind'" class="inline-flex items-center gap-1 align-middle"><IconArrowDown :size="11" class="shrink-0" />{{ commitsText(state.behind) }} para baixar de {{ state.upstream }}</span>
        <template v-else-if="state.kind === 'ahead'">{{ commitsText(state.ahead) }} para subir para {{ state.upstream }}</template>
        <template v-else>em dia com {{ state.upstream }}</template>
      </span>
      <span data-test="prop-branch-checked">{{ status }}{{ status ? ' · ' : '' }}<button
        type="button"
        data-test="prop-branch-fetch"
        :disabled="busy"
        class="cursor-pointer text-fg-muted underline decoration-line-strong underline-offset-2 hover:text-fg disabled:cursor-default disabled:opacity-50 disabled:hover:text-fg-muted"
        @click="git.fetchNow(projectId)"
      >{{ failed ? 'Tentar de novo' : 'Verificar agora' }}</button></span>
      <span v-if="repo.fetch_error" data-test="prop-branch-fetch-error" :title="repo.fetch_error" class="truncate">{{ repo.fetch_error }}</span>
    </template>
    <span v-if="requestError" data-test="prop-branch-fetch-failure" role="alert" class="text-diff-del-fg">{{ requestError }}</span>
  </div>
</template>
