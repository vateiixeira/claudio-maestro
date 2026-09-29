<script setup lang="ts">
import { computed, ref } from 'vue'
import { ApiError, answerPrompt, errorMessage } from '../../api/http'
import { prettyJson, str } from '../../conversation/tool'
import type { PermissionPrompt, PromptDecision } from '../../types/conversation'

const props = defineProps<{ sessionId: string; prompt: PermissionPrompt }>()
const emit = defineEmits<{ resolved: [] }>()

const sending = ref<PromptDecision | null>(null)
const error = ref<string | null>(null)

const toolLabel = computed(() => props.prompt.display_name || props.prompt.tool_name)
const heading = computed(() => {
  if (props.prompt.title) return props.prompt.title
  const name = props.prompt.tool_name
  if (name === 'Bash') return 'Permissão para rodar comando'
  if (name === 'Edit' || name === 'Write' || name === 'MultiEdit') return 'Permissão para alterar arquivo'
  if (name === 'Read') return 'Permissão para ler arquivo'
  return `Permissão para usar ${toolLabel.value}`
})
const subject = computed(() => {
  const input = props.prompt.input ?? {}
  return str(input.command) || str(input.file_path) || str(input.path) || str(input.url) || prettyJson(input)
})

async function decide(decision: PromptDecision) {
  if (sending.value) return
  sending.value = decision
  error.value = null
  try {
    await answerPrompt(props.sessionId, props.prompt.prompt_id, decision)
    emit('resolved')
  } catch (e) {
    // 409: already answered (maybe in another tab). Nothing to warn about.
    if (e instanceof ApiError && e.status === 409) emit('resolved')
    else error.value = errorMessage(e)
  } finally {
    sending.value = null
  }
}
</script>

<template>
  <div data-test="permission-card" class="flex flex-col gap-3 rounded-[10px] border border-secondary/50 bg-secondary/10 p-3.5">
    <div class="flex items-center gap-2">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 text-secondary" aria-hidden="true"><path d="M12 3 2 20h20L12 3z" /><line x1="12" y1="10" x2="12" y2="14" /><line x1="12" y1="17" x2="12" y2="17.01" /></svg>
      <span class="font-semibold text-secondary-soft">{{ heading }}</span>
      <span class="ml-auto font-mono text-xs text-secondary-soft">{{ toolLabel }}</span>
    </div>
    <pre class="m-0 max-h-60 overflow-auto rounded-md border border-line bg-bg px-3 py-2.5 font-mono text-xs leading-relaxed whitespace-pre-wrap break-all text-fg">{{ subject }}</pre>
    <p v-if="prompt.description" class="m-0 text-xs text-secondary-soft">{{ prompt.description }}</p>
    <p v-if="error" role="alert" class="m-0 text-sm text-diff-del-fg">{{ error }}</p>
    <div class="flex flex-col gap-2">
      <div class="flex gap-2">
        <button
          type="button"
          data-test="allow-once"
          class="h-11 grow cursor-pointer rounded-lg border-none bg-secondary text-sm font-semibold text-secondary-fg disabled:cursor-default disabled:opacity-60"
          :disabled="sending !== null"
          @click="decide('allow_once')"
        >
          Permitir uma vez
        </button>
        <button
          type="button"
          data-test="deny"
          class="h-11 grow cursor-pointer rounded-lg border border-secondary/50 bg-transparent text-sm font-medium text-secondary-soft disabled:cursor-default disabled:opacity-60"
          :disabled="sending !== null"
          @click="decide('deny')"
        >
          Negar
        </button>
      </div>
      <button
        v-if="prompt.can_always"
        type="button"
        data-test="allow-always"
        class="h-11 cursor-pointer rounded-lg border border-line-strong bg-transparent text-sm font-medium text-fg disabled:cursor-default disabled:opacity-60"
        :disabled="sending !== null"
        @click="decide('allow_always')"
      >
        Permitir sempre
      </button>
    </div>
  </div>
</template>
