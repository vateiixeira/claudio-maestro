<script setup lang="ts">
import { computed, ref } from 'vue'
import { ApiError, answerPrompt, errorMessage } from '../../api/http'
import DiffLines from './DiffLines.vue'
import { diffCounts, toolDiff } from '../../conversation/diff'
import { describePermissionRule } from '../../conversation/permissionRule'
import { prettyJson, str } from '../../conversation/tool'
import type { PermissionPrompt, PromptDecision } from '../../types/conversation'

const props = defineProps<{ sessionId: string; prompt: PermissionPrompt; live?: boolean }>()
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

// Edit, Write and MultiEdit show what would change, not the raw input. Long diffs start folded.
const DIFF_PREVIEW = 12
const diffLines = computed(() => {
  const name = props.prompt.tool_name
  if (name !== 'Edit' && name !== 'Write' && name !== 'MultiEdit') return []
  return toolDiff(name, props.prompt.input ?? {}, null)
})
const counts = computed(() => diffCounts(diffLines.value))
const diffExpanded = ref(false)
const folded = computed(() => !diffExpanded.value && diffLines.value.length > DIFF_PREVIEW)
const shownDiff = computed(() => (folded.value ? diffLines.value.slice(0, DIFF_PREVIEW) : diffLines.value))
const diffPath = computed(() => str(props.prompt.input?.file_path))
const ruleHints = computed(() => (props.prompt.can_always ? describePermissionRule(props.prompt.suggestions) : []))

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
  <div data-test="permission-card" class="flex flex-col gap-3 rounded-xl border border-secondary/50 bg-panel p-3.5" :class="{ 'animate-decision': live }">
    <div class="flex items-center gap-2">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0 text-secondary" aria-hidden="true"><path d="M12 3 2 20h20L12 3z" /><line x1="12" y1="10" x2="12" y2="14" /><line x1="12" y1="17" x2="12" y2="17.01" /></svg>
      <span class="font-semibold text-secondary-soft">{{ heading }}</span>
      <span class="ml-auto font-mono text-xs text-secondary-soft">{{ toolLabel }}</span>
    </div>
    <div v-if="diffLines.length" data-test="permission-diff" class="overflow-hidden rounded-[8px] border border-line bg-bg">
      <div class="flex items-center gap-2 border-b border-line px-3 py-2">
        <span data-test="diff-path" class="min-w-0 grow truncate font-mono text-xs text-info-soft">{{ diffPath }}</span>
        <span data-test="diff-counts" class="shrink-0 font-mono text-xs"><span class="text-diff-add-fg">+{{ counts.added }}</span> <span class="text-diff-del-fg">−{{ counts.removed }}</span></span>
      </div>
      <div class="max-h-80 overflow-y-auto py-1.5"><DiffLines :lines="shownDiff" /></div>
      <button
        v-if="folded"
        type="button"
        data-test="diff-expand"
        class="min-h-8 w-full cursor-pointer border-0 border-t border-line bg-transparent px-3 py-1 text-left text-xs text-fg-muted hover:bg-elevated hover:text-fg focus-visible:outline-2 focus-visible:outline-primary"
        @click="diffExpanded = true"
      >
        Ver as {{ diffLines.length }} linhas
      </button>
    </div>
    <pre v-else class="m-0 max-h-60 overflow-auto rounded-md border border-line bg-bg px-3 py-2.5 font-mono text-xs leading-relaxed whitespace-pre-wrap break-all text-fg">{{ subject }}</pre>
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
      <p v-if="ruleHints.length" data-test="rule-hint" class="m-0 flex flex-col gap-1 text-xs text-fg-muted">
        <span v-for="(hint, index) in ruleHints" :key="index" class="flex flex-wrap items-center gap-x-1.5 gap-y-1">
          <span>{{ hint.lead }}</span>
          <code v-for="chip in hint.chips" :key="chip" data-test="rule-chip" class="rounded-[6px] border border-line bg-bg px-1.5 py-0.5 font-mono break-all text-fg">{{ chip }}</code>
          <span v-if="hint.scope">· {{ hint.scope }}</span>
        </span>
      </p>
    </div>
  </div>
</template>
