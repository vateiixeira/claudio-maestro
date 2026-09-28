<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { errorMessage, listDirs } from '../api/http'
import { tildePath } from '../format'
import type { DirEntry, DirListing } from '../types/api'

defineProps<{ selected: string | null }>()

const emit = defineEmits<{
  /** A folder was picked. `display` is the path with `~` for the home folder. */
  select: [folder: { name: string; path: string; display: string }]
}>()

const listing = ref<DirListing | null>(null)
const home = ref<string | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

// "~" plus one crumb per folder below home.
const crumbs = computed(() => {
  const current = listing.value
  if (!current || !home.value) return []
  const base = home.value
  const parts = current.path === base ? [] : current.path.slice(base.length + 1).split('/')
  return [
    { label: '~', path: base },
    ...parts.map((part, index) => ({ label: part, path: `${base}/${parts.slice(0, index + 1).join('/')}` })),
  ]
})

async function load(path?: string): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const result = await listDirs(path)
    if (path === undefined) home.value = result.path
    listing.value = result
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

function select(entry: DirEntry): void {
  emit('select', { name: entry.name, path: entry.path, display: tildePath(entry.path, home.value) })
}

async function enter(entry: DirEntry): Promise<void> {
  select(entry)
  await load(entry.path)
}

onMounted(() => load())
</script>

<template>
  <div class="flex min-w-0 flex-col gap-2.5">
    <div class="font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Escolha a pasta</div>

    <div class="flex min-w-0 items-center gap-1 font-mono text-[13px]">
      <button
        type="button"
        data-test="dir-up"
        class="flex size-11 shrink-0 items-center justify-center rounded-md text-fg-muted hover:bg-card hover:text-fg disabled:opacity-40 disabled:hover:bg-transparent"
        aria-label="Pasta de cima"
        title="Pasta de cima"
        :disabled="!listing?.parent || loading"
        @click="listing?.parent && load(listing.parent)"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M12 19V5M5 12l7-7 7 7" />
        </svg>
      </button>
      <nav aria-label="Caminho da pasta" class="flex min-w-0 flex-wrap items-center gap-0.5">
        <template v-for="(crumb, index) in crumbs" :key="crumb.path">
          <span v-if="index > 0" class="text-fg-muted/50" aria-hidden="true">/</span>
          <button
            type="button"
            data-test="crumb"
            class="h-11 rounded-md px-2.5 hover:bg-card"
            :class="index === crumbs.length - 1 ? 'text-fg' : 'text-fg-muted'"
            :aria-current="index === crumbs.length - 1 ? 'location' : undefined"
            @click="load(crumb.path)"
          >
            {{ crumb.label }}
          </button>
        </template>
      </nav>
    </div>

    <p v-if="error" class="rounded-lg border border-secondary/40 bg-card px-3.5 py-2.5 text-sm text-secondary-soft" role="alert">
      {{ error }}
    </p>

    <div
      v-else
      data-test="dir-list"
      class="flex max-h-[352px] min-h-11 flex-col overflow-y-auto rounded-lg border border-line bg-bg"
      :aria-busy="loading"
    >
      <p v-if="listing && listing.entries.length === 0" class="px-3.5 py-3 text-sm text-fg-muted">
        Nenhuma subpasta aqui.
      </p>
      <button
        v-for="entry in listing?.entries ?? []"
        :key="entry.path"
        type="button"
        data-test="dir"
        class="flex min-h-11 shrink-0 items-center gap-2.5 border-b border-line px-3.5 text-left text-sm last:border-b-0"
        :class="selected === entry.path ? 'bg-primary/10 font-semibold text-fg' : 'text-fg hover:bg-card'"
        :aria-pressed="selected === entry.path"
        @click="select(entry)"
        @dblclick="enter(entry)"
        @keydown.enter.prevent="enter(entry)"
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          :class="selected === entry.path ? 'stroke-primary' : 'stroke-fg-muted'"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
        </svg>
        <span data-test="dir-name" class="min-w-0 flex-1 truncate">{{ entry.name }}</span>
        <span
          v-if="entry.git"
          class="font-mono text-xs font-normal"
          :class="selected === entry.path ? 'text-primary-soft' : 'text-fg-muted'"
        >git</span>
      </button>
    </div>

    <p class="text-xs text-fg-muted">Clique duas vezes em uma pasta, ou tecle Enter, para entrar nela.</p>
  </div>
</template>
