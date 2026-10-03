<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import type { AwayCounts } from '../../conversation/awayCounts'
import { formatActivity } from '../../format'
import { useMinuteClock } from '../../minuteClock'
import { useDigestStore } from '../../stores/digest'
import IconClose from '../icons/IconClose.vue'

// Card at the top of a conversation the user comes back to after a while: what happened meanwhile.
// The counts come from the conversation items; Feito and Falta from the summary the digest agent
// keeps. It only reads a saved summary: the model runs only when the user clicks "Resumir agora".
const props = defineProps<{ sessionId: string; since: number; counts: AwayCounts }>()
defineEmits<{ close: []; 'view-changes': []; 'jump-to-end': [] }>()

const LIST_LIMIT = 4

const store = useDigestStore()
// The shared clock only says when to read the time again; its own value can be older than the card.
const tick = useMinuteClock()
const nowDate = computed(() => { void tick.value; return new Date() })

const title = computed(() => `Enquanto você estava fora · ${formatActivity(props.since, nowDate.value)}`)

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`
const countsText = computed(() => {
  const { turns, actions, files } = props.counts
  const parts: string[] = []
  if (turns) parts.push(plural(turns, 'turno', 'turnos'))
  if (actions) parts.push(plural(actions, 'ação', 'ações'))
  if (files) parts.push(plural(files, 'arquivo alterado', 'arquivos alterados'))
  return parts.join(' · ')
})

const enabled = computed(() => store.status?.enabled === true)
const loaded = computed(() => props.sessionId in store.digests)
const digest = computed(() => store.digests[props.sessionId] ?? null)
const hasSummary = computed(() => !!digest.value && digest.value.phases.length > 0)
const showColumns = computed(() => enabled.value && hasSummary.value)
const pending = computed(() => !!store.pending[props.sessionId])
const requestError = computed(() => store.errors[props.sessionId] ?? null)

const doneAll = computed(() => (digest.value?.phases ?? []).flatMap((p) => p.done))
const pendingAll = computed(() => (digest.value?.phases ?? []).flatMap((p) => p.pending))
// Feito shows the latest items; Falta the first ones (what comes next).
const doneShown = computed(() => doneAll.value.slice(-LIST_LIMIT))
const doneHidden = computed(() => doneAll.value.length - doneShown.value.length)
const pendingShown = computed(() => pendingAll.value.slice(0, LIST_LIMIT))
const pendingHidden = computed(() => pendingAll.value.length - pendingShown.value.length)

// Reading a saved summary is free; loading it again after `invalidate()` too.
watch([() => props.sessionId, loaded, () => store.epoch], ([id, isLoaded]) => {
  if (!isLoaded) void store.load(id)
}, { immediate: true })
onMounted(() => {
  if (!store.status) void store.refreshStatus()
})
</script>

<template>
  <section data-test="away-summary" aria-labelledby="away-title" class="flex flex-col gap-3 rounded-xl border border-line-strong bg-panel p-3.5">
    <header class="flex items-center gap-2">
      <h2 id="away-title" data-test="away-title" class="cap m-0 min-w-0 grow truncate text-fg-subtle">{{ title }}</h2>
      <button
        type="button"
        data-test="away-close"
        aria-label="Fechar"
        title="Fechar"
        class="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-md text-fg-muted hover:bg-card hover:text-fg focus-visible:outline-2 focus-visible:outline-primary"
        @click="$emit('close')"
      >
        <IconClose :size="14" />
      </button>
    </header>

    <p v-if="countsText" data-test="away-counts" class="m-0 text-sm text-fg">{{ countsText }}</p>

    <div v-if="showColumns" class="grid gap-3 sm:grid-cols-2">
      <div data-test="away-done" class="flex min-w-0 flex-col gap-1 text-fg-muted">
        <p class="cap m-0">Feito</p>
        <ul v-if="doneShown.length" class="m-0 flex list-none flex-col gap-0.5 p-0 text-[0.8125rem] leading-normal">
          <li v-for="(item, i) in doneShown" :key="i" class="min-w-0">{{ item }}</li>
        </ul>
        <p v-else class="m-0 text-[0.8125rem]">Nada concluído ainda</p>
        <p v-if="doneHidden > 0" data-test="away-done-more" class="m-0 text-xs text-fg-subtle">+ {{ doneHidden }} antes</p>
      </div>
      <div data-test="away-pending" class="flex min-w-0 flex-col gap-1 text-fg">
        <p data-test="away-pending-title" class="cap m-0 text-secondary-soft">Falta</p>
        <ul v-if="pendingShown.length" class="m-0 flex list-none flex-col gap-0.5 p-0 text-[0.8125rem] leading-normal">
          <li v-for="(item, i) in pendingShown" :key="i" class="min-w-0">{{ item }}</li>
        </ul>
        <p v-else class="m-0 text-[0.8125rem] text-fg-muted">Nada pendente</p>
        <p v-if="pendingHidden > 0" data-test="away-pending-more" class="m-0 text-xs text-fg-subtle">+ {{ pendingHidden }} depois</p>
      </div>
    </div>

    <p v-if="requestError" data-test="away-error" role="alert" class="m-0 text-xs text-diff-del-fg">{{ requestError }}</p>

    <footer class="flex flex-wrap items-center gap-2">
      <span v-if="showColumns && digest?.read_at" data-test="away-digest-age" class="text-xs text-fg-muted">Resumo de {{ formatActivity(digest.read_at, nowDate) }}</span>
      <button
        type="button"
        data-test="away-digest-request"
        class="h-8 cursor-pointer rounded-md border border-line-strong px-2.5 text-xs font-medium text-fg hover:bg-card focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-40"
        :disabled="pending"
        @click="store.request(sessionId)"
      >{{ pending ? 'Resumindo…' : 'Resumir agora' }}</button>
      <span class="grow" />
      <button
        type="button"
        data-test="away-view-changes"
        class="h-8 cursor-pointer rounded-md px-2.5 text-xs font-medium text-fg-muted hover:bg-card hover:text-fg focus-visible:outline-2 focus-visible:outline-primary"
        @click="$emit('view-changes')"
      >Ver alterações</button>
      <button
        type="button"
        data-test="away-jump"
        class="h-8 cursor-pointer rounded-md border border-line-strong bg-card px-2.5 text-xs font-medium text-fg hover:bg-elevated focus-visible:outline-2 focus-visible:outline-primary"
        @click="$emit('jump-to-end')"
      >Ir para o fim</button>
    </footer>
  </section>
</template>
