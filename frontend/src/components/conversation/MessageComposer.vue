<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { errorMessage, interruptSession, sendMessage } from '../../api/http'
import type { SessionState } from '../../types/api'

const props = defineProps<{ sessionId: string; state: SessionState }>()

const text = ref('')
const sending = ref(false)
const interrupting = ref(false)
const error = ref<string | null>(null)
const textarea = ref<HTMLTextAreaElement | null>(null)

const busy = computed(() => props.state === 'running' || props.state === 'awaiting_decision')

// Grows with the text up to 40% of the column, then scrolls.
function resize() {
  const el = textarea.value
  if (!el) return
  const column = el.closest('section') as HTMLElement | null
  const max = (column?.clientHeight || window.innerHeight) * 0.4
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, max)}px`
  el.style.overflowY = el.scrollHeight > max ? 'auto' : 'hidden'
}

function insertNewline() {
  const el = textarea.value
  if (!el) return
  const start = el.selectionStart ?? text.value.length
  const end = el.selectionEnd ?? start
  text.value = text.value.slice(0, start) + '\n' + text.value.slice(end)
  el.value = text.value
  el.setSelectionRange(start + 1, start + 1)
  nextTick(resize)
}

function onKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.isComposing || event.keyCode === 229) return
  if (event.shiftKey) return // browser inserts the line break
  event.preventDefault()
  if (event.ctrlKey || event.metaKey || event.altKey) insertNewline()
  else void send()
}

async function send() {
  const message = text.value
  if (!message.trim() || sending.value) return
  sending.value = true
  error.value = null
  try {
    await sendMessage(props.sessionId, message)
    // Only clear if the user did not keep typing meanwhile.
    if (text.value === message) text.value = ''
    nextTick(resize)
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    sending.value = false
  }
}

async function interrupt() {
  interrupting.value = true
  error.value = null
  try {
    await interruptSession(props.sessionId)
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    interrupting.value = false
  }
}
</script>

<template>
  <div class="flex flex-col gap-2.5">
    <p v-if="error" role="alert" class="m-0 text-sm text-diff-del-fg">{{ error }}</p>
    <div class="flex items-end gap-2">
      <label :for="`msg-${sessionId}`" class="sr-only">Mensagem para a sessão</label>
      <textarea
        :id="`msg-${sessionId}`"
        ref="textarea"
        v-model="text"
        rows="1"
        placeholder="Mensagem"
        class="min-h-11 min-w-0 grow resize-none overflow-hidden rounded-lg border border-line-strong bg-panel px-3.5 py-[11px] font-sans text-sm leading-normal text-fg outline-none focus:border-fg-muted"
        @input="resize"
        @keydown="onKeydown"
      />
      <button
        v-if="busy"
        type="button"
        data-test="interrupt"
        class="flex h-11 cursor-pointer items-center gap-2 rounded-lg border border-line-strong bg-elevated px-3.5 text-sm font-medium text-fg disabled:opacity-60"
        :disabled="interrupting"
        @click="interrupt"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="2" /></svg>
        Interromper
      </button>
      <button
        type="button"
        data-test="send"
        class="h-11 cursor-pointer rounded-lg border-none bg-primary px-4 text-sm font-semibold text-primary-fg disabled:cursor-default disabled:opacity-50"
        :disabled="sending || !text.trim()"
        @click="send"
      >
        Enviar
      </button>
    </div>
    <span class="self-end font-mono text-xs text-fg-muted">Enter envia · Ctrl+Enter quebra linha</span>
  </div>
</template>
