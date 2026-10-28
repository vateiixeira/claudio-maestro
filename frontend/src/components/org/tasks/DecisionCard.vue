<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ApiError, answerDecision, errorMessage } from '../../../api/http'
import { formatRunDate } from '../../../org'
import { AREA, BTN_PRIMARY, ERROR } from '../styles'
import type { Decision } from '../../../types/org'

// A decision an agent asks of the person: the question, the options as buttons (or a free answer when there are
// none) and, once answered, the answer with its receipt. Answering twice (double click, another tab) is refused by
// the server with 409; the card then says it was already answered and sends nothing more.
const props = defineProps<{ decision: Decision }>()
const emit = defineEmits<{ answered: [decision: Decision]; stale: [] }>()

const chosen = ref<string | null>(null)
const free = ref('')
const busy = ref(false)
const error = ref<string | null>(null)
const already = ref(false)
/** What the server returned for my answer; it wins over the pending decision of the props until they catch up. */
const mine = ref<Decision | null>(null)

const current = computed(() => mine.value ?? props.decision)
const open = computed(() => current.value.status === 'pending' && !already.value)
const hasOptions = computed(() => current.value.options.length > 0)
const answer = computed(() => (hasOptions.value ? chosen.value ?? '' : free.value).trim())
const canSend = computed(() => open.value && answer.value.length > 0 && !busy.value)

watch(() => props.decision.id, () => {
  chosen.value = null
  free.value = ''
  error.value = null
  already.value = false
  mine.value = null
})

// The decision came back reloaded and no longer pending: show its answer, not the "already answered" notice.
watch(() => props.decision.status, (status) => { if (status !== 'pending') already.value = false })

async function send(): Promise<void> {
  if (!canSend.value) return
  busy.value = true
  error.value = null
  try {
    const decision = await answerDecision(props.decision.id, answer.value)
    mine.value = decision
    emit('answered', decision)
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      already.value = true
      emit('stale')
    } else {
      error.value = errorMessage(e)
    }
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <article
    data-test="decision-card"
    :data-decision-id="decision.id"
    :data-status="current.status"
    :aria-labelledby="`decision-q-${decision.id}`"
    class="flex min-w-0 flex-col gap-2 rounded-lg border bg-panel p-3"
    :class="open ? 'border-secondary' : 'border-line'"
  >
    <p v-if="open" class="m-0 inline-flex items-center gap-1.5 text-xs font-medium text-secondary-soft">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3.5 2.5 20h19L12 3.5z" /><path d="M12 10v4M12 17v.01" /></svg>
      Aguardando você
    </p>
    <p :id="`decision-q-${decision.id}`" class="m-0 text-sm text-fg [overflow-wrap:anywhere]">{{ current.question }}</p>

    <template v-if="open">
      <div v-if="hasOptions" role="group" aria-label="Opções" class="flex flex-wrap gap-2">
        <button
          v-for="option in current.options"
          :key="option"
          type="button"
          data-test="decision-option"
          :aria-pressed="chosen === option"
          :disabled="busy"
          class="min-h-8 cursor-pointer rounded-lg border px-3 py-1 text-left text-sm focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-default disabled:opacity-50"
          :class="chosen === option ? 'border-fg-muted bg-card font-medium text-fg' : 'border-line-strong bg-transparent text-fg-muted hover:bg-card hover:text-fg'"
          @click="chosen = option"
        >{{ option }}</button>
      </div>
      <label v-else class="flex flex-col gap-1 text-xs text-fg-muted">
        Sua resposta
        <textarea v-model="free" rows="3" :class="AREA" :disabled="busy" />
      </label>
      <p v-if="error" role="alert" :class="ERROR">{{ error }}</p>
      <div>
        <button type="button" data-test="decision-submit" :class="BTN_PRIMARY" :disabled="!canSend" @click="send">{{ busy ? 'Enviando…' : 'Responder' }}</button>
      </div>
    </template>

    <p v-else-if="already" data-test="decision-already" role="status" class="m-0 text-sm text-fg-muted">Já respondida. A resposta chegou antes da sua; a tarefa mostra o que foi decidido.</p>
    <p v-else-if="current.status === 'expired'" data-test="decision-expired" class="m-0 text-sm text-fg-muted">Expirada. Ninguém respondeu a tempo e o agente seguiu sem esta decisão.</p>
    <template v-else>
      <p class="m-0 text-sm text-fg-muted">
        <span class="text-xs text-fg-subtle">Resposta</span><br />
        <span data-test="decision-answer" class="text-fg [overflow-wrap:anywhere]">{{ current.answer }}</span>
      </p>
      <p class="m-0 flex flex-wrap gap-x-3 text-xs text-fg-subtle">
        <span v-if="current.receipt" data-test="decision-receipt">Recibo <span class="font-mono">{{ current.receipt.slice(0, 8) }}</span></span>
        <time v-if="current.answered_at" :datetime="new Date(current.answered_at * 1000).toISOString()">{{ formatRunDate(current.answered_at) }}</time>
      </p>
    </template>
  </article>
</template>
