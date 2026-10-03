<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { ApiError, answerPrompt, errorMessage } from '../../api/http'
import { onCodeCopyClick } from '../../conversation/codeCopy'
import { renderMarkdown } from '../../conversation/markdown'
import { parseSteps } from '../../plan/parseSteps'
import type { PermissionPrompt } from '../../types/conversation'

const props = defineProps<{ sessionId: string; prompt: PermissionPrompt }>()
const emit = defineEmits<{ resolved: [] }>()

const html = computed(() => renderMarkdown(props.prompt.plan ?? ''))
const steps = computed(() => parseSteps(props.prompt.plan ?? ''))
const asking = ref(false)
const message = ref('')
const sending = ref(false)
const error = ref<string | null>(null)
const field = ref<HTMLTextAreaElement | null>(null)
// Notes by step number, and the step whose one-line field is open.
const notes = ref<Record<number, string>>({})
const editing = ref<number | null>(null)

const hasNote = (n: number) => !!notes.value[n]?.trim()
const request = computed(() => {
  if (!steps.value.length) return message.value.trim()
  const lines = steps.value.filter((step) => hasNote(step.number)).map((step) => `Passo ${step.number}: ${notes.value[step.number]!.trim()}`)
  if (message.value.trim()) lines.push(message.value.trim())
  return lines.join('\n')
})

// Only one step note is open at a time, so a single element ref is enough.
const stepInput = ref<HTMLInputElement | null>(null)
const setStepInput = (el: unknown) => { stepInput.value = (el as HTMLInputElement | null) ?? null }

async function toggleStep(n: number) {
  editing.value = editing.value === n ? null : n
  if (editing.value === null) return
  await nextTick()
  stepInput.value?.focus()
}

async function openChanges() {
  asking.value = true
  await nextTick()
  if (!steps.value.length) field.value?.focus()
}

async function send(decision: 'approve' | 'reject') {
  const text = request.value
  if (sending.value || (decision === 'reject' && !text)) return
  sending.value = true
  error.value = null
  try {
    await answerPrompt(props.sessionId, props.prompt.prompt_id, decision, decision === 'reject' ? { message: text } : {})
    emit('resolved')
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) emit('resolved')
    else error.value = errorMessage(e)
  } finally {
    sending.value = false
  }
}
</script>

<template>
  <div data-test="plan-card" class="flex flex-col gap-3 rounded-xl border border-secondary/50 bg-panel p-3.5">
    <div class="flex items-center gap-2">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 text-secondary" aria-hidden="true"><path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" /></svg>
      <span class="font-semibold text-secondary-soft">Plano para aprovar</span>
    </div>
    <!-- Safe: markdown-it runs with `html: false`. -->
    <div class="markdown max-h-96 overflow-auto rounded-md border border-line bg-bg px-3 py-2.5 text-sm text-fg" @click="onCodeCopyClick" v-html="html" />
    <p v-if="error" role="alert" class="m-0 text-sm text-diff-del-fg">{{ error }}</p>
    <div v-if="asking" class="flex flex-col gap-2">
      <div v-if="steps.length" data-test="plan-steps" class="flex flex-col gap-0.5 rounded-md border border-line bg-bg p-1.5">
        <p class="m-0 px-1.5 pb-1 text-xs text-fg-muted">Clique num passo para comentar</p>
        <div v-for="step in steps" :key="step.number" class="flex flex-col">
          <button
            type="button"
            data-test="plan-step"
            class="flex cursor-pointer items-baseline gap-2 rounded-md border-none bg-transparent px-1.5 py-1 text-left text-sm text-fg hover:bg-panel disabled:cursor-default"
            :aria-expanded="editing === step.number"
            :disabled="sending"
            @click="toggleStep(step.number)"
          >
            <span
              data-test="step-number"
              class="w-5 shrink-0 text-right font-mono text-xs tabular-nums"
              :class="hasNote(step.number) ? 'font-semibold text-secondary-soft' : 'text-fg-subtle'"
            >{{ step.number }}</span>
            <span class="min-w-0 break-words">{{ step.title }}</span>
          </button>
          <input
            v-if="editing === step.number"
            :ref="setStepInput"
            v-model="notes[step.number]"
            data-test="step-note"
            type="text"
            placeholder="O que mudar neste passo"
            aria-label="O que mudar neste passo"
            class="ml-9 mr-1.5 mb-1 rounded-md border border-line-strong bg-panel px-2.5 py-1.5 text-sm text-fg"
            :disabled="sending"
            @keydown.enter.prevent="editing = null"
            @keydown.esc.stop="editing = null"
          />
          <p
            v-else-if="hasNote(step.number)"
            data-test="step-note-text"
            class="m-0 mb-1 ml-9 mr-1.5 whitespace-pre-wrap break-words border-l-2 border-secondary/60 pl-2.5 text-sm text-fg-muted"
          >{{ notes[step.number]!.trim() }}</p>
        </div>
      </div>
      <label class="flex flex-col gap-1 text-xs text-fg-muted">
        {{ steps.length ? 'Comentário geral (opcional)' : 'O que mudar no plano' }}
        <textarea
          ref="field"
          v-model="message"
          :data-test="steps.length ? 'general-comment' : 'reject-message'"
          :rows="steps.length ? 2 : 3"
          :required="!steps.length"
          class="rounded-md border border-line-strong bg-panel px-2.5 py-2 text-sm text-fg"
          :disabled="sending"
        />
      </label>
      <div class="flex gap-2">
        <button
          type="button"
          data-test="send-reject"
          class="h-11 grow cursor-pointer rounded-lg border-none bg-secondary text-sm font-semibold text-secondary-fg disabled:cursor-default disabled:opacity-60"
          :disabled="sending || !request"
          @click="send('reject')"
        >
          Enviar pedido
        </button>
        <button
          type="button"
          class="h-11 grow cursor-pointer rounded-lg border border-line-strong bg-transparent text-sm font-medium text-fg disabled:opacity-60"
          :disabled="sending"
          @click="asking = false"
        >
          Cancelar
        </button>
      </div>
    </div>
    <div v-else class="flex gap-2">
      <button
        type="button"
        data-test="approve"
        class="h-11 grow cursor-pointer rounded-lg border-none bg-secondary text-sm font-semibold text-secondary-fg disabled:cursor-default disabled:opacity-60"
        :disabled="sending"
        @click="send('approve')"
      >
        Aprovar plano
      </button>
      <button
        type="button"
        data-test="request-changes"
        class="h-11 grow cursor-pointer rounded-lg border border-secondary/50 bg-transparent text-sm font-medium text-secondary-soft disabled:cursor-default disabled:opacity-60"
        :disabled="sending"
        @click="openChanges"
      >
        Pedir mudanças
      </button>
    </div>
  </div>
</template>
