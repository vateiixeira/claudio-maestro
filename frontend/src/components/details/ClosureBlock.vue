<!-- frontend/src/components/details/ClosureBlock.vue -->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { CLOSURE_BADGE_CLASS, CLOSURE_LABELS, shownVerdict } from '../../closure'
import { errorMessage } from '../../api/http'
import { formatActivity } from '../../format'
import { useClosureStore } from '../../stores/closure'
import { useSessionsStore } from '../../stores/sessions'

const props = defineProps<{ sessionId: string }>()
const store = useClosureStore()
const sessions = useSessionsStore()

const session = computed(() => sessions.find(props.sessionId))
const verdict = computed(() => (session.value ? shownVerdict(session.value) : null))
const closure = computed(() => store.closures[props.sessionId] ?? null)
const loaded = computed(() => props.sessionId in store.closures)
const busy = computed(() => store.busy[props.sessionId] ?? null)
const error = computed(() => store.errors[props.sessionId] ?? closure.value?.error ?? null)
const finished = computed(() => session.value?.display_state === 'finished')
const visible = computed(() => !finished.value && (!!verdict.value || !!error.value))
const finishing = ref(false)
const finishError = ref<string | null>(null)

// Loads on session change, after invalidate() and when the verdict in the list changes.
watch([() => props.sessionId, loaded, () => store.epoch, () => session.value?.closure_verdict], ([id, isLoaded], old) => {
  const verdictChanged = old && old[3] !== session.value?.closure_verdict
  if (!isLoaded || verdictChanged) void store.load(id as string)
}, { immediate: true })

async function finish() {
  finishing.value = true
  finishError.value = null
  try {
    await sessions.setFinished(props.sessionId, true)
  } catch (e) {
    finishError.value = errorMessage(e)
  } finally {
    finishing.value = false
  }
}
</script>

<template>
  <section v-if="visible" data-test="details-closure" aria-labelledby="closure-title" class="flex flex-col gap-2 rounded-lg border border-line-strong bg-card p-3">
    <div class="flex items-center gap-2">
      <h4 id="closure-title" class="m-0 font-mono text-[0.65625rem] font-semibold tracking-[0.08em] text-fg-subtle uppercase">Fechamento</h4>
      <span v-if="verdict" data-test="closure-badge" class="rounded-full border px-2 text-[0.6875rem]" :class="CLOSURE_BADGE_CLASS[verdict]">{{ CLOSURE_LABELS[verdict] }}</span>
    </div>

    <template v-if="verdict && closure">
      <div v-if="closure.user_actions.length" class="flex flex-col gap-1">
        <p class="m-0 text-[0.71875rem] font-semibold text-fg">Falta você fazer</p>
        <ul class="m-0 flex list-none flex-col gap-1 p-0 text-[0.8125rem] leading-normal font-medium text-fg">
          <li v-for="(item, i) in closure.user_actions" :key="`${i}-${item}`" data-test="closure-action" class="flex items-start gap-2">
            <span class="mt-[5px] size-2.5 shrink-0 rounded-full border border-fg-muted" aria-hidden="true" />
            <span class="min-w-0 grow">{{ item }}</span>
            <button
              type="button"
              data-test="closure-done"
              class="h-7 shrink-0 rounded-md border border-line-strong px-2 text-xs text-fg-muted hover:bg-elevated hover:text-fg disabled:opacity-40"
              :aria-label="`Já fiz: ${item}`"
              :disabled="busy !== null"
              @click="store.resolve(sessionId, item)"
            >Já fiz</button>
          </li>
        </ul>
      </div>
      <div v-if="closure.missing.length" class="flex flex-col gap-1">
        <p class="m-0 text-[0.71875rem] font-semibold text-fg">Falta implementar</p>
        <ul class="m-0 flex list-none flex-col gap-1 p-0 text-[0.8125rem] leading-normal text-fg">
          <li v-for="(item, i) in closure.missing" :key="`${i}-${item}`" data-test="closure-missing" class="flex items-start gap-2">
            <span class="mt-[5px] size-2.5 shrink-0 rounded-full border border-fg-muted" aria-hidden="true" />
            <span class="min-w-0">{{ item }}</span>
          </li>
        </ul>
      </div>
      <p v-if="closure.checked_at" data-test="closure-checked" class="m-0 text-xs text-fg-muted">
        Verificado {{ formatActivity(closure.checked_at) }}<template v-if="closure.evidence"> · {{ closure.evidence }}</template>
      </p>
    </template>

    <button
      v-if="verdict === 'can_close'"
      type="button"
      data-test="closure-finish"
      class="h-8 self-start rounded-md border border-primary/50 px-2.5 text-xs font-medium text-primary-soft hover:bg-primary-tint disabled:opacity-40"
      :disabled="finishing"
      @click="finish"
    >Finalizar conversa</button>
    <p v-if="finishError" role="alert" class="m-0 text-xs text-diff-del-fg">{{ finishError }}</p>

    <p v-if="error" data-test="closure-error" role="alert" class="m-0 text-xs text-diff-del-fg">{{ error }}</p>
  </section>
</template>
