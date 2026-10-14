<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { errorMessage, getBranches } from '../../../api/http'
import { formatActivity } from '../../../format'
import type { BranchList, BranchRef, RepoDetails } from '../../../types/api'

const props = defineProps<{ projectId: number; repo: RepoDetails; mode: 'switch' | 'merge'; canMerge: boolean }>()
const emit = defineEmits<{ switch: [branch: BranchRef]; merge: [branch: BranchRef]; create: [name: string]; close: [restoreFocus?: boolean] }>()

type Item =
  | { kind: 'create'; id: string }
  | { kind: 'branch'; id: string; branch: BranchRef; remote: boolean; current: boolean }

const listId = useId()
const list = ref<BranchList | null>(null)
const error = ref<string | null>(null)
const query = ref('')
const active = ref(0)
const search = ref<HTMLInputElement | null>(null)
const panel = ref<HTMLElement | null>(null)
const branchName = computed(() => props.repo.branch ?? props.repo.head ?? '')

// On the document, not on the input: Esc closes with the focus anywhere inside the menu.
function onDocumentKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Escape') return
  event.preventDefault()
  emit('close')
}
onBeforeUnmount(() => document.removeEventListener('keydown', onDocumentKeydown))

/** Focus went to another element: the menu closes and leaves the focus where it went. */
function onFocusout(event: FocusEvent): void {
  const next = event.relatedTarget
  if (next instanceof Node && !panel.value?.contains(next)) emit('close', false)
}

onMounted(async () => {
  document.addEventListener('keydown', onDocumentKeydown)
  await nextTick()
  search.value?.focus()
  try {
    list.value = await getBranches(props.projectId, props.repo.path)
  } catch (e) {
    error.value = errorMessage(e)
  }
})

const needle = computed(() => query.value.trim().toLowerCase())
const matches = (b: BranchRef) => !needle.value || b.name.toLowerCase().includes(needle.value)
// A remote branch that a local one already tracks shows only as the local one.
const tracked = computed(() => new Set((list.value?.local ?? []).map((b) => b.upstream).filter(Boolean)))
const items = computed<Item[]>(() => {
  // Nothing to choose, by key or click, until the list is here.
  if (!list.value) return []
  const current = list.value?.current ?? null
  const locals = (list.value?.local ?? []).filter(matches)
    .filter((b) => props.mode === 'switch' || b.ref !== current)
    .map((b, i): Item => ({ kind: 'branch', id: `${listId}-l${i}`, branch: b, remote: false, current: b.ref === current }))
  const remotes = (list.value?.remote ?? []).filter((b) => !tracked.value.has(b.name)).filter(matches)
    .map((b, i): Item => ({ kind: 'branch', id: `${listId}-r${i}`, branch: b, remote: true, current: false }))
  return [...(props.mode === 'switch' ? [{ kind: 'create', id: `${listId}-create` } as Item] : []), ...locals, ...remotes]
})
watch(items, (now) => { active.value = Math.min(active.value, Math.max(now.length - 1, 0)) })
const localItems = computed(() => items.value.filter((i) => i.kind === 'branch' && !i.remote))
const remoteItems = computed(() => items.value.filter((i) => i.kind === 'branch' && i.remote))
const indexOf = (item: Item) => items.value.indexOf(item)
const createLabel = computed(() => (query.value.trim() ? `Criar branch ${query.value.trim()}` : `Criar branch a partir de ${branchName.value}…`))

function choose(item: Item): void {
  if (item.kind === 'create') emit('create', query.value.trim())
  else if (item.current) emit('close')
  else if (props.mode === 'merge') emit('merge', item.branch)
  else emit('switch', item.branch)
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    active.value = Math.min(active.value + 1, items.value.length - 1)
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    active.value = Math.max(active.value - 1, 0)
  } else if (event.key === 'Enter') {
    event.preventDefault()
    const item = items.value[active.value]
    if (item) choose(item)
  }
}

const rowClass = (item: Item) => [
  'group flex min-h-7 cursor-pointer items-center gap-2 rounded px-2 text-[0.8125rem]',
  indexOf(item) === active.value ? 'bg-elevated' : 'hover:bg-elevated',
]
</script>

<template>
  <div class="fixed inset-0 z-40" data-test="branch-menu-backdrop" @click="emit('close')" />
  <div ref="panel" data-test="branch-menu" class="absolute top-7 right-0 z-50 flex w-80 max-w-[calc(100vw-32px)] flex-col rounded-lg border border-line-strong bg-panel p-1 shadow-2xl" @focusout="onFocusout">
    <input
      ref="search"
      v-model="query"
      type="text"
      data-test="branch-search"
      role="combobox"
      aria-expanded="true"
      :aria-controls="list ? listId : undefined"
      :aria-activedescendant="items[active]?.id"
      :aria-label="mode === 'merge' ? `Escolher a branch para mesclar em ${branchName}` : 'Buscar branch'"
      :placeholder="mode === 'merge' ? `Mesclar em ${branchName}…` : 'Trocar para…'"
      class="h-[30px] w-full rounded-md border border-line-strong bg-surface px-2 text-[0.8125rem] text-fg placeholder:text-fg-subtle focus:border-fg-muted focus:outline-none"
      @keydown="onKeydown"
    >
    <p v-if="error" role="alert" class="m-0 px-2 py-1.5 text-xs text-diff-del-fg">{{ error }}</p>
    <p v-else-if="!list" class="m-0 px-2 py-1.5 text-xs text-fg-muted">Carregando…</p>
    <ul v-else :id="listId" role="listbox" class="m-0 mt-1 flex max-h-80 list-none flex-col overflow-y-auto p-0">
      <template v-for="item in items" :key="item.id">
        <li v-if="item.kind === 'create'" :id="item.id" role="option" :aria-selected="indexOf(item) === active" data-test="branch-create" :class="rowClass(item)" @click="choose(item)">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true" class="shrink-0 text-fg-muted"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
          <span class="truncate">{{ createLabel }}</span>
        </li>
      </template>
      <li v-if="localItems.length" role="presentation" class="px-2 pt-1.5 pb-0.5 text-xs text-fg-subtle">Locais</li>
      <template v-for="item in localItems" :key="item.id">
        <li v-if="item.kind === 'branch'" :id="item.id" role="option" :aria-selected="indexOf(item) === active" data-test="branch-item" :data-name="item.branch.name" :class="rowClass(item)" @click="choose(item)">
          <span class="min-w-0 grow truncate font-mono text-xs" :class="item.current ? 'text-fg' : 'text-fg-muted'">{{ item.branch.name }}</span>
          <span v-if="item.current" class="shrink-0 text-xs text-fg-subtle">atual</span>
          <span v-else class="shrink-0 text-xs text-fg-subtle">{{ formatActivity(Date.parse(item.branch.date) / 1000) }}</span>
          <button
            v-if="mode === 'switch' && canMerge && !item.current"
            type="button"
            tabindex="-1"
            data-test="branch-merge"
            :aria-label="`Mesclar ${item.branch.name} em ${branchName}`"
            :title="`Mesclar ${item.branch.name} em ${branchName}`"
            class="flex size-[22px] shrink-0 items-center justify-center rounded text-fg-muted opacity-0 group-hover:opacity-100 hover:bg-card hover:text-fg"
            :class="{ 'opacity-100': indexOf(item) === active }"
            @click.stop="emit('merge', item.branch)"
          ><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="18" cy="18" r="3" /><circle cx="6" cy="6" r="3" /><path d="M6 21V9a9 9 0 0 0 9 9" /></svg></button>
        </li>
      </template>
      <li v-if="remoteItems.length" role="presentation" class="px-2 pt-1.5 pb-0.5 text-xs text-fg-subtle">Remotas</li>
      <template v-for="item in remoteItems" :key="item.id">
        <li v-if="item.kind === 'branch'" :id="item.id" role="option" :aria-selected="indexOf(item) === active" data-test="branch-item" :data-name="item.branch.name" :class="rowClass(item)" @click="choose(item)">
          <span class="min-w-0 grow truncate font-mono text-xs text-fg-muted">{{ item.branch.name }}</span>
          <span v-if="mode === 'switch'" class="shrink-0 text-xs text-fg-subtle">cria local</span>
          <button
            v-if="mode === 'switch' && canMerge"
            type="button"
            tabindex="-1"
            data-test="branch-merge"
            :aria-label="`Mesclar ${item.branch.name} em ${branchName}`"
            :title="`Mesclar ${item.branch.name} em ${branchName}`"
            class="flex size-[22px] shrink-0 items-center justify-center rounded text-fg-muted opacity-0 group-hover:opacity-100 hover:bg-card hover:text-fg"
            :class="{ 'opacity-100': indexOf(item) === active }"
            @click.stop="emit('merge', item.branch)"
          ><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="18" cy="18" r="3" /><circle cx="6" cy="6" r="3" /><path d="M6 21V9a9 9 0 0 0 9 9" /></svg></button>
        </li>
      </template>
      <li v-if="mode === 'merge' && items.length === 0" role="presentation" class="px-2 py-1.5 text-xs text-fg-muted">Nenhuma branch com esse nome.</li>
    </ul>
  </div>
</template>
