<script setup lang="ts">
import { formatActivity } from '../../format'
import type { RepoCommit } from '../../types/api'

defineProps<{ commits: RepoCommit[] }>()

function commitTime(date: string): string {
  const ms = Date.parse(date)
  return Number.isNaN(ms) ? '' : formatActivity(ms / 1000)
}
</script>

<template>
  <section class="flex flex-col gap-1.5" aria-label="Últimos commits">
    <h4 class="m-0 font-mono text-[11px] tracking-[0.08em] text-fg-muted uppercase">Últimos commits</h4>
    <p v-if="commits.length === 0" class="m-0 text-sm text-fg-muted">Sem commits</p>
    <ul v-else class="m-0 flex list-none flex-col p-0">
      <li
        v-for="commit in commits"
        :key="commit.full_hash"
        data-test="commit"
        class="flex min-h-8 items-center gap-3 text-sm"
      >
        <span class="shrink-0 font-mono text-xs text-fg-muted">{{ commit.hash }}</span>
        <span class="min-w-0 grow truncate" :title="commit.subject">{{ commit.subject }}</span>
        <span
          v-if="commit.pushed === false"
          data-test="commit-unpushed"
          title="Este commit ainda não subiu para o upstream"
          class="shrink-0 font-mono text-xs text-secondary-soft"
        ><span aria-hidden="true">↑</span><span class="sr-only">não subiu</span></span>
        <span class="shrink-0 truncate text-xs text-fg-muted">{{ commit.author }}</span>
        <span class="w-16 shrink-0 text-right font-mono text-xs text-fg-muted">{{ commitTime(commit.date) }}</span>
      </li>
    </ul>
  </section>
</template>
