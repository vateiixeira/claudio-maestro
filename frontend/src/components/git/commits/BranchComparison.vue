<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { errorMessage, getBranchComparison } from '../../../api/http'
import type { BranchComparison } from '../../../types/api'
import IconChevron from '../../icons/IconChevron.vue'
import HistoryRefMenu from './HistoryRefMenu.vue'
import ComparisonDirection from './ComparisonDirection.vue'

const props = withDefaults(defineProps<{
  projectId: number; repoPath: string; headRef: string | null; branch: string
  defaultBase: string | null; userEmail: string | null; revision?: number; active?: boolean
}>(), { active: true })
const storageKey = () => `maestro.gitComparison:${props.projectId}:${props.repoPath}`
function savedBase(): string | null {
  try { return localStorage.getItem(storageKey()) || props.defaultBase } catch { return props.defaultBase }
}
const base = ref(savedBase())
const open = ref(false)
const choosing = ref(false)
const loading = ref(false)
const error = ref<string | null>(null)
const comparison = ref<BranchComparison | null>(null)
const expanded = ref({ ahead: false, behind: false })
const short = (name: string) => name.replace(/^refs\/(heads|remotes)\//, '')
const label = computed(() => `Comparar ${props.branch} com ${base.value ? short(base.value) : 'outra branch'}`)
let stale = false
let generation = 0
let controller: AbortController | undefined
function cancel(): void { generation++; controller?.abort(); controller = undefined; loading.value = false }
onBeforeUnmount(cancel)

async function load(): Promise<void> {
  if (!props.active) { stale = true; return }
  stale = false
  cancel()
  comparison.value = null
  expanded.value = { ahead: false, behind: false }
  if (!base.value || !open.value) return
  const mine = generation
  controller = new AbortController()
  loading.value = true
  error.value = null
  try {
    const result = await getBranchComparison(props.projectId, props.repoPath, base.value, props.headRef, controller.signal)
    if (mine === generation) comparison.value = result
  } catch (e) {
    if (mine === generation) error.value = errorMessage(e)
  } finally { if (mine === generation) loading.value = false }
}
function toggle(): void {
  if (!base.value) { choosing.value = true; return }
  open.value = !open.value
  if (open.value) void load()
  else { cancel(); comparison.value = null; choosing.value = false }
}
function select(value: string): void {
  base.value = value
  try { localStorage.setItem(storageKey(), value) } catch { /* Storage may be unavailable. */ }
  choosing.value = false
  open.value = true
  void load()
}
watch(() => props.active, (active) => {
  if (!active) {
    if (loading.value) { stale = true; cancel() }
    return
  }
  if (stale) void load()
})
watch(() => [props.projectId, props.repoPath, props.headRef, props.branch, props.revision], (now, previous) => {
  if (now[0] !== previous[0] || now[1] !== previous[1]) base.value = savedBase()
  void load()
})
</script>

<template>
  <div data-test="branch-comparison" class="relative flex min-w-0 flex-col">
    <div class="flex min-h-6 min-w-0 items-center gap-1">
      <button type="button" data-test="comparison-toggle" :aria-expanded="open" class="flex min-w-0 grow items-center gap-1.5 text-left text-xs text-fg-muted hover:text-fg" :title="label" @click="toggle">
        <IconChevron :open="open" :size="12" class="shrink-0 text-fg-subtle" /><span class="truncate">{{ label }}</span>
      </button>
      <button type="button" data-test="comparison-select" :aria-expanded="choosing" aria-haspopup="listbox" aria-label="Escolher base de comparação" title="Escolher base sem trocar de branch" class="shrink-0 rounded px-1.5 text-xs text-fg-muted hover:bg-elevated" @click="choosing = !choosing">Base…</button>
      <button v-if="open && comparison" type="button" aria-label="Atualizar comparação" class="shrink-0 rounded px-1.5 text-xs text-fg-muted hover:bg-elevated" @click="load">Atualizar</button>
    </div>
    <HistoryRefMenu v-if="choosing" :project-id="projectId" :repo-path="repoPath" :current="base" @select="select" @close="choosing = false" />
    <div v-if="open" class="min-w-0 pl-4">
      <p v-if="loading" class="m-0 py-1 text-xs text-fg-muted">Carregando comparação…</p>
      <p v-if="error" role="alert" class="m-0 py-1 text-xs text-diff-del-fg">{{ error }} <button type="button" class="underline" @click="load">Tentar novamente</button></p>
      <template v-if="comparison">
        <p class="m-0 py-1 text-xs text-fg-subtle">Comparação das referências atuais.</p>
        <p v-if="comparison.notice" class="m-0 py-1 text-xs text-fg-muted">{{ comparison.notice }}</p>
        <div v-for="direction in (['ahead', 'behind'] as const)" :key="direction">
          <button type="button" :data-test="`comparison-${direction}-toggle`" :aria-expanded="expanded[direction]" class="flex min-h-6 w-full items-center gap-1.5 text-left text-xs text-fg-muted hover:text-fg" @click="expanded[direction] = !expanded[direction]">
            <IconChevron :open="expanded[direction]" :size="12" class="text-fg-subtle" />
            {{ direction === 'ahead' ? 'Somente nesta branch' : 'Somente na base' }} · {{ direction === 'ahead' ? comparison.ahead_count : comparison.behind_count }} {{ (direction === 'ahead' ? comparison.ahead_count : comparison.behind_count) === 1 ? 'commit' : 'commits' }}
          </button>
          <ComparisonDirection v-if="expanded[direction]" :key="`${comparison.head_sha}:${comparison.base_sha}:${direction}`" :project-id="projectId" :repo-path="repoPath" :comparison="comparison" :direction="direction" :user-email="userEmail" />
        </div>
      </template>
    </div>
  </div>
</template>
