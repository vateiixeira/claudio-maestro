<!-- frontend/src/components/details/DigestSection.vue -->
<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { PHASE_KIND_LABELS, digestUpdatedText } from '../../digestConfig'
import ClosureBlock from './ClosureBlock.vue'
import { useDigestStore } from '../../stores/digest'
import { useMinuteClock } from '../../minuteClock'

const props = defineProps<{ sessionId: string }>()
const store = useDigestStore()
const clock = useMinuteClock()

const loaded = computed(() => props.sessionId in store.digests)
const digest = computed(() => store.digests[props.sessionId] ?? null)
const pending = computed(() => !!store.pending[props.sessionId])
const requestError = computed(() => store.errors[props.sessionId] ?? null)
const hasSummary = computed(() => !!digest.value && (!!digest.value.short || digest.value.phases.length > 0))

// Loads when the session changes and again after `invalidate()` (socket came back).
watch([() => props.sessionId, loaded, () => store.epoch], ([id, isLoaded]) => {
  if (!isLoaded) void store.load(id)
}, { immediate: true })

// Phases get a stable key from kind and title (a repeated pair gets a counter), so a new
// digest with reordered phases keeps each expansion on its own phase.
const phases = computed(() => {
  const seen = new Map<string, number>()
  return (digest.value?.phases ?? []).map((phase) => {
    const base = `${phase.kind}:${phase.title}`
    const count = seen.get(base) ?? 0
    seen.set(base, count + 1)
    return { phase, key: count ? `${base}#${count}` : base }
  })
})

// Phases whose done steps are expanded, by phase key; reset when the session changes.
const expanded = reactive<Record<string, boolean>>({})
watch(() => props.sessionId, () => { for (const key of Object.keys(expanded)) delete expanded[key] })
const stepsLabel = (count: number) => `${count} ${count === 1 ? 'passo' : 'passos'}`

const fileName = (path: string) => path.split('/').pop() ?? path
</script>

<template>
  <section data-test="details-digest" aria-labelledby="digest-title" class="flex flex-col gap-3.5">
    <div class="flex items-center gap-2.5">
      <h3 id="digest-title" class="m-0 flex items-center gap-2 font-mono text-[0.65625rem] font-semibold tracking-[0.08em] text-fg-subtle uppercase">
        Resumo
        <span v-if="digest?.plan_done" data-test="digest-plan-done" class="rounded-full border border-primary/40 px-2 font-sans text-[0.6875rem] font-normal tracking-normal normal-case text-primary-soft">Plano concluído</span>
      </h3>
      <span v-if="loaded && digest?.read_at" data-test="digest-read-at" class="ml-auto text-xs text-fg-muted">{{ digestUpdatedText(digest.read_at, new Date(clock)) }}</span>
    </div>

    <div v-if="!loaded" class="flex items-center justify-between gap-2 text-sm">
      <span :class="requestError ? 'text-diff-del-fg' : 'text-fg-muted'" :role="requestError ? 'alert' : undefined">{{ requestError ?? 'Carregando…' }}</span>
      <button v-if="requestError" type="button" class="h-8 rounded-md px-2 text-xs text-fg-muted hover:bg-card hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary" @click="store.load(sessionId)">Tentar de novo</button>
    </div>
    <template v-else>
      <p v-if="!hasSummary" data-test="digest-empty" class="m-0 text-sm text-fg-muted">Ainda não resumida</p>
      <ClosureBlock v-if="!hasSummary" :session-id="sessionId" />
      <template v-else>
        <p v-if="digest?.short" data-test="digest-short" class="m-0 text-base leading-normal text-fg">{{ digest.short }}</p>
        <ClosureBlock :session-id="sessionId" />
        <ol
          data-test="digest-timeline"
          class="relative m-0 mt-1.5 flex list-none flex-col gap-[1.375rem] p-0 before:absolute before:top-2.5 before:bottom-2.5 before:left-[0.59375rem] before:w-px before:bg-line before:content-['']"
        >
          <li
            v-for="{ phase, key } in phases"
            :key="key"
            data-test="digest-phase"
            class="relative flex items-start gap-3"
          >
            <span
              data-test="digest-phase-node"
              :data-status="phase.status"
              class="flex size-5 flex-none items-center justify-center rounded-full border-[1.5px] bg-bg"
              :class="phase.status === 'done' ? 'border-line-strong text-fg-muted' : 'border-primary'"
              aria-hidden="true"
            >
              <svg v-if="phase.status === 'done'" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5 10 17 19 7" /></svg>
              <span v-else class="size-1.5 rounded-full bg-primary" />
            </span>
            <div class="flex min-w-0 flex-1 flex-col gap-1.5">
              <div class="flex items-center gap-2 leading-5">
                <span data-test="digest-phase-kind" class="font-mono text-[0.65625rem] font-semibold tracking-[0.08em] text-fg-subtle uppercase">{{ PHASE_KIND_LABELS[phase.kind] }}</span>
                <span data-test="digest-phase-status" class="sr-only">{{ phase.status === 'open' ? 'Aberta' : 'Concluída' }}</span>
              </div>
              <p class="m-0 text-sm leading-snug font-medium" :class="phase.status === 'done' ? 'text-fg-muted' : 'text-fg'">{{ phase.title }}</p>
              <p v-if="phase.ref" class="m-0 truncate font-mono text-[0.71875rem] text-fg-subtle" :title="phase.ref">{{ fileName(phase.ref) }}</p>
              <div v-if="phase.pending.length" class="mt-0.5 flex flex-col gap-1">
                <p class="m-0 text-[0.71875rem] font-semibold text-fg">Falta</p>
                <ul class="m-0 flex list-none flex-col gap-1 p-0 text-[0.8125rem] leading-normal font-medium text-fg">
                  <li v-for="(item, j) in phase.pending" :key="j" class="flex items-start gap-2">
                    <span data-test="digest-pending-marker" class="mt-[5px] size-2.5 shrink-0 rounded-full border border-fg-muted" aria-hidden="true" />
                    <span class="min-w-0">{{ item }}</span>
                  </li>
                </ul>
              </div>
              <template v-if="phase.done.length">
                <button
                  type="button"
                  data-test="digest-steps-toggle"
                  :aria-expanded="!!expanded[key]"
                  class="inline-flex h-6 w-fit items-center gap-1 rounded text-[0.78125rem] text-fg-muted hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                  @click="expanded[key] = !expanded[key]"
                >
                  {{ expanded[key] ? stepsLabel(phase.done.length) : `Ver ${phase.done.length === 1 ? '' : 'os '}${stepsLabel(phase.done.length)}` }}
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path :d="expanded[key] ? 'm6 9 6 6 6-6' : 'm9 6 6 6-6 6'" /></svg>
                </button>
                <ul v-if="expanded[key]" class="m-0 flex list-none flex-col gap-2 p-0 text-[0.8125rem] leading-normal text-fg-muted">
                  <li v-for="(item, j) in phase.done" :key="j" data-test="digest-done-item" class="flex items-start gap-2.5">
                    <span data-test="digest-done-marker" class="mt-2.5 h-px w-2 shrink-0 bg-fg-subtle" aria-hidden="true" />
                    <span class="min-w-0">{{ item }}</span>
                  </li>
                </ul>
              </template>
            </div>
          </li>
        </ol>
      </template>

      <p v-if="digest?.error || requestError" data-test="digest-error" role="alert" class="m-0 text-xs text-diff-del-fg">{{ requestError ?? digest?.error }}</p>

      <div class="flex items-center justify-end gap-2">
        <button
          type="button"
          data-test="digest-request"
          class="h-8 rounded-md border border-line-strong px-2.5 text-xs font-medium text-fg hover:bg-card focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-40"
          :disabled="pending"
          @click="store.request(sessionId)"
        >{{ pending ? 'Resumindo…' : 'Resumir agora' }}</button>
      </div>
    </template>
  </section>
</template>
