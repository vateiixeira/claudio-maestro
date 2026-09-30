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
    <h3 id="digest-title" class="m-0 flex items-center gap-2 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">
      Resumo
      <span v-if="digest?.plan_done" data-test="digest-plan-done" class="rounded border border-primary/40 px-1.5 font-sans text-[11px] tracking-normal normal-case text-primary-soft">Plano concluído</span>
    </h3>

    <div v-if="!loaded" class="flex items-center justify-between gap-2 text-sm">
      <span :class="requestError ? 'text-secondary-soft' : 'text-fg-muted'" :role="requestError ? 'alert' : undefined">{{ requestError ?? 'Carregando…' }}</span>
      <button v-if="requestError" type="button" class="h-8 rounded-md px-2 text-xs text-fg-muted hover:bg-card hover:text-fg" @click="store.load(sessionId)">Tentar de novo</button>
    </div>
    <template v-else>
      <p v-if="!hasSummary" data-test="digest-empty" class="m-0 text-sm text-fg-muted">Ainda não resumida</p>
      <template v-else>
        <p v-if="digest?.short" data-test="digest-short" class="m-0 text-sm font-medium text-fg">{{ digest.short }}</p>
        <ol class="m-0 flex list-none flex-col gap-3 p-0">
          <li
            v-for="(phase, i) in digest?.phases ?? []"
            :key="i"
            data-test="digest-phase"
            class="flex flex-col gap-1.5 rounded-lg border border-line p-3"
            :class="phase.status === 'done' ? 'bg-bg' : 'bg-card'"
          >
            <div class="flex items-center gap-2 text-xs text-fg-muted">
              <span class="font-mono uppercase">{{ PHASE_KIND_LABELS[phase.kind] }}</span>
              <span aria-hidden="true">·</span>
              <span :class="phase.status === 'open' ? 'text-primary-soft' : ''">{{ phase.status === 'open' ? 'Aberta' : 'Concluída' }}</span>
            </div>
            <p class="m-0 text-sm text-fg">{{ phase.title }}</p>
            <p v-if="phase.ref" class="m-0 truncate font-mono text-xs text-fg-muted" :title="phase.ref">{{ fileName(phase.ref) }}</p>
            <div v-if="phase.done.length" class="text-xs">
              <p class="m-0 text-fg-muted">Feito</p>
              <ul class="m-0 pl-4 text-fg"><li v-for="(item, j) in phase.done" :key="j">{{ item }}</li></ul>
            </div>
            <div v-if="phase.pending.length" class="text-xs">
              <p class="m-0 text-fg-muted">Falta</p>
              <ul class="m-0 pl-4 text-fg"><li v-for="(item, j) in phase.pending" :key="j">{{ item }}</li></ul>
            </div>
          </li>
        </ol>
      </template>

      <p v-if="digest?.error || requestError" data-test="digest-error" role="alert" class="m-0 text-xs text-secondary-soft">{{ requestError ?? digest?.error }}</p>

      <div class="flex items-center justify-between gap-2">
        <span v-if="digest?.read_at" data-test="digest-read-at" class="text-xs text-fg-muted">Lido {{ formatActivity(digest.read_at) }}</span>
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
