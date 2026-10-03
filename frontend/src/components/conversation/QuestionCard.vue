<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { ApiError, answerPrompt, errorMessage } from '../../api/http'
import type { PermissionPrompt, PromptDecision } from '../../types/conversation'

const props = defineProps<{ sessionId: string; prompt: PermissionPrompt; live?: boolean }>()
const emit = defineEmits<{ resolved: [] }>()

const questions = computed(() => props.prompt.questions ?? [])
// Per question: the chosen labels and the free text.
const chosen = reactive<string[][]>(questions.value.map(() => []))
const other = reactive<string[]>(questions.value.map(() => ''))

const sending = ref<PromptDecision | null>(null)
const error = ref<string | null>(null)

function answerOf(index: number): string | string[] | null {
  const text = (other[index] ?? '').trim()
  if (text) return questions.value[index]?.multiSelect ? [text] : text
  const labels = chosen[index] ?? []
  if (!labels.length) return null
  return questions.value[index]?.multiSelect ? [...labels] : labels[0]!
}

const complete = computed(() => questions.value.length > 0 && questions.value.every((_, i) => answerOf(i) !== null))

function pick(index: number, label: string, multi: boolean, checked: boolean) {
  const current = chosen[index] ?? []
  if (!multi) chosen[index] = checked ? [label] : []
  else chosen[index] = checked ? [...current.filter((l) => l !== label), label] : current.filter((l) => l !== label)
}

async function send(decision: 'answer' | 'deny') {
  if (sending.value || (decision === 'answer' && !complete.value)) return
  sending.value = decision
  error.value = null
  try {
    if (decision === 'answer') {
      const answers: Record<string, string | string[]> = {}
      questions.value.forEach((q, i) => (answers[q.question] = answerOf(i)!))
      await answerPrompt(props.sessionId, props.prompt.prompt_id, 'answer', { answers })
    } else {
      await answerPrompt(props.sessionId, props.prompt.prompt_id, 'deny')
    }
    emit('resolved')
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) emit('resolved')
    else error.value = errorMessage(e)
  } finally {
    sending.value = null
  }
}
</script>

<template>
  <div data-test="question-card" class="flex flex-col gap-3 rounded-xl border border-secondary/50 bg-panel p-3.5" :class="{ 'animate-decision': live }">
    <div class="flex items-center gap-2">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 text-secondary" aria-hidden="true"><circle cx="12" cy="12" r="10" /><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3" /><line x1="12" y1="17" x2="12" y2="17.01" /></svg>
      <span class="font-semibold text-secondary-soft">Pergunta do Claude</span>
    </div>
    <fieldset
      v-for="(q, qi) in questions"
      :key="qi"
      class="m-0 flex flex-col gap-2 rounded-md border border-line bg-bg p-3"
    >
      <legend class="px-1 text-sm text-fg">
        <span v-if="q.header" class="mr-2 rounded-full bg-secondary/20 px-1.5 py-0.5 font-mono text-xs text-secondary-soft">{{ q.header }}</span>
        {{ q.question }}
      </legend>
      <label
        v-for="opt in q.options"
        :key="opt.label"
        class="flex cursor-pointer items-start gap-2 rounded-md px-1 py-1 hover:bg-elevated"
      >
        <input
          :type="q.multiSelect ? 'checkbox' : 'radio'"
          :name="`${prompt.prompt_id}-${qi}`"
          :value="opt.label"
          :checked="chosen[qi]?.includes(opt.label)"
          class="mt-1 accent-secondary"
          :disabled="sending !== null"
          @change="pick(qi, opt.label, !!q.multiSelect, ($event.target as HTMLInputElement).checked)"
        />
        <span class="flex flex-col">
          <span class="text-sm text-fg">{{ opt.label }}</span>
          <span v-if="opt.description" class="text-xs text-fg-subtle">{{ opt.description }}</span>
        </span>
      </label>
      <label class="flex flex-col gap-1 text-xs text-fg-muted">
        Outra resposta
        <input
          v-model="other[qi]"
          type="text"
          data-test="other-answer"
          class="h-9 rounded-md border border-line-strong bg-panel px-2.5 text-sm text-fg"
          :disabled="sending !== null"
          @keydown.enter.prevent="send('answer')"
        />
        <span v-if="q.multiSelect" data-test="other-hint">Se preenchida, substitui as opções marcadas.</span>
      </label>
    </fieldset>
    <p v-if="error" role="alert" class="m-0 text-sm text-diff-del-fg">{{ error }}</p>
    <div class="flex gap-2">
      <button
        type="button"
        data-test="answer"
        class="h-11 grow cursor-pointer rounded-lg border-none bg-secondary text-sm font-semibold text-secondary-fg disabled:cursor-default disabled:opacity-60"
        :disabled="sending !== null || !complete"
        @click="send('answer')"
      >
        Responder
      </button>
      <button
        type="button"
        data-test="deny"
        class="h-11 grow cursor-pointer rounded-lg border border-secondary/50 bg-transparent text-sm font-medium text-secondary-soft disabled:cursor-default disabled:opacity-60"
        :disabled="sending !== null"
        @click="send('deny')"
      >
        Recusar
      </button>
    </div>
  </div>
</template>
