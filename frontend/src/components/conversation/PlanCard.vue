<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { ApiError, answerPrompt, errorMessage } from '../../api/http'
import { renderMarkdown } from '../../conversation/markdown'
import type { PermissionPrompt } from '../../types/conversation'

const props = defineProps<{ sessionId: string; prompt: PermissionPrompt }>()
const emit = defineEmits<{ resolved: [] }>()

const html = computed(() => renderMarkdown(props.prompt.plan ?? ''))
const asking = ref(false)
const message = ref('')
const sending = ref(false)
const error = ref<string | null>(null)
const field = ref<HTMLTextAreaElement | null>(null)

async function openChanges() {
  asking.value = true
  await nextTick()
  field.value?.focus()
}

async function send(decision: 'approve' | 'reject') {
  const text = message.value.trim()
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
  <div data-test="plan-card" class="flex flex-col gap-3 rounded-[10px] border border-secondary/50 bg-panel p-3.5">
    <div class="flex items-center gap-2">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 text-secondary" aria-hidden="true"><path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" /></svg>
      <span class="font-semibold text-secondary-soft">Plano para aprovar</span>
    </div>
    <!-- Safe: markdown-it runs with `html: false`. -->
    <div class="markdown max-h-96 overflow-auto rounded-md border border-line bg-bg px-3 py-2.5 text-sm text-fg" v-html="html" />
    <p v-if="error" role="alert" class="m-0 text-sm text-diff-del-fg">{{ error }}</p>
    <div v-if="asking" class="flex flex-col gap-2">
      <label class="flex flex-col gap-1 text-xs text-fg-muted">
        O que mudar no plano
        <textarea
          ref="field"
          v-model="message"
          data-test="reject-message"
          rows="3"
          required
          class="rounded-md border border-line-strong bg-panel px-2.5 py-2 text-sm text-fg"
          :disabled="sending"
        />
      </label>
      <div class="flex gap-2">
        <button
          type="button"
          data-test="send-reject"
          class="h-11 grow cursor-pointer rounded-lg border-none bg-secondary text-sm font-semibold text-secondary-fg disabled:cursor-default disabled:opacity-60"
          :disabled="sending || !message.trim()"
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
