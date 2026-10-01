<!-- frontend/src/components/details/DigestSection.vue -->
<script setup lang="ts">
import { computed, watch } from 'vue'
import { PHASE_KIND_LABELS } from '../../digestConfig'
import { formatActivity } from '../../format'
import { useDigestStore } from '../../stores/digest'

const props = defineProps<{ sessionId: string }>()
const store = useDigestStore()

const loaded = computed(() => props.sessionId in store.digests)
const digest = computed(() => store.digests[props.sessionId] ?? null)
const pending = computed(() => !!store.pending[props.sessionId])
const requestError = computed(() => store.errors[props.sessionId] ?? null)
const hasSummary = computed(() => !!digest.value && (!!digest.value.short || digest.value.phases.length > 0))

// Loads when the session changes and again after `invalidate()` (socket came back).
watch([() => props.sessionId, loaded, () => store.epoch], ([id, isLoaded]) => {
  if (!isLoaded) void store.load(id)
}, { immediate: true })

const fileName = (path: string) => path.split('/').pop() ?? path
</script>

<template>
  <section data-test="details-digest" aria-labelledby="digest-title" class="flex flex-col gap-3">
    <h3 id="digest-title" class="m-0 flex items-center gap-2 font-mono text-[10.5px] font-semibold tracking-[0.08em] text-fg-subtle uppercase">
      Resumo
      <span v-if="digest?.plan_done" data-test="digest-plan-done" class="rounded border border-primary/40 px-1.5 font-sans text-[11px] font-normal tracking-normal normal-case text-primary-soft">Plano concluído</span>
    </h3>

    <div v-if="!loaded" class="flex items-center justify-between gap-2 text-sm">
      <span :class="requestError ? 'text-diff-del-fg' : 'text-fg-muted'" :role="requestError ? 'alert' : undefined">{{ requestError ?? 'Carregando…' }}</span>
      <button v-if="requestError" type="button" class="h-8 rounded-md px-2 text-xs text-fg-muted hover:bg-card hover:text-fg" @click="store.load(sessionId)">Tentar de novo</button>
    </div>
    <template v-else>
      <p v-if="!hasSummary" data-test="digest-empty" class="m-0 text-sm text-fg-muted">Ainda não resumida</p>
      <template v-else>
        <p v-if="digest?.short" data-test="digest-short" class="m-0 text-sm leading-normal text-fg">{{ digest.short }}</p>
        <ol class="m-0 flex list-none flex-col gap-3 p-0">
          <li
            v-for="(phase, i) in digest?.phases ?? []"
            :key="i"
            data-test="digest-phase"
            class="flex flex-col gap-1.5 rounded-lg border p-3"
            :class="phase.status === 'done' ? 'border-line bg-bg' : 'border-line-strong bg-card'"
          >
            <div class="flex items-center gap-2">
              <span class="font-mono text-[10.5px] font-semibold tracking-[0.08em] text-fg-subtle uppercase">{{ PHASE_KIND_LABELS[phase.kind] }}</span>
              <span
                data-test="digest-phase-status"
                class="ml-auto flex items-center gap-1 rounded-full border border-line-strong px-2 py-px text-[11.5px] font-medium"
                :class="phase.status === 'open' ? 'bg-elevated text-fg' : 'text-fg-muted'"
              >
                <svg v-if="phase.status !== 'open'" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5" /></svg>
                {{ phase.status === 'open' ? 'Aberta' : 'Concluída' }}
              </span>
            </div>
            <p class="m-0 text-sm leading-snug" :class="phase.status === 'done' ? 'text-fg-muted' : 'text-fg'">{{ phase.title }}</p>
            <p v-if="phase.ref" class="m-0 truncate font-mono text-[11.5px] text-fg-subtle" :title="phase.ref">{{ fileName(phase.ref) }}</p>
            <div v-if="phase.pending.length" class="mt-0.5 flex flex-col gap-1">
              <p class="m-0 text-[11.5px] font-semibold text-fg">Falta</p>
              <ul class="m-0 flex list-none flex-col gap-1 p-0 text-[13px] leading-normal font-medium text-fg">
                <li v-for="(item, j) in phase.pending" :key="j" class="flex items-start gap-2">
                  <span class="mt-[5px] size-2.5 shrink-0 rounded-full border border-fg-muted" aria-hidden="true" />
                  <span class="min-w-0">{{ item }}</span>
                </li>
              </ul>
            </div>
            <div v-if="phase.done.length" class="mt-0.5 flex flex-col gap-1">
              <p class="m-0 text-[11.5px] text-fg-subtle">Feito</p>
              <ul class="m-0 pl-4 text-[12.5px] leading-normal text-fg-muted"><li v-for="(item, j) in phase.done" :key="j">{{ item }}</li></ul>
            </div>
          </li>
        </ol>
      </template>

      <p v-if="digest?.error || requestError" data-test="digest-error" role="alert" class="m-0 text-xs text-diff-del-fg">{{ requestError ?? digest?.error }}</p>

      <div class="flex items-center justify-between gap-2">
        <span v-if="digest?.read_at" data-test="digest-read-at" class="text-xs text-fg-muted">Resumido {{ formatActivity(digest.read_at) }}</span>
        <span v-else />
        <button
          type="button"
          data-test="digest-request"
          class="h-8 rounded-md border border-line-strong px-2.5 text-xs font-medium text-fg hover:bg-card disabled:cursor-not-allowed disabled:opacity-40"
          :disabled="pending"
          @click="store.request(sessionId)"
        >{{ pending ? 'Resumindo…' : 'Resumir agora' }}</button>
      </div>
    </template>
  </section>
</template>
