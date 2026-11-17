<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { errorMessage, getAgentMemory, putAgentMemory } from '../../../api/http'
import { renderMarkdown } from '../../../conversation/markdown'
import { MEMORY_MAX } from '../../../org'
import { useOrgStore } from '../../../stores/org'
import { AREA, BTN_PRIMARY, BTN_SMALL, ERROR } from '../styles'
import { formatCount, memoryLevel } from './helpers'

// What the agent remembers between runs: a free text it rewrites and you can edit too. It opens as rendered markdown;
// "Editar" swaps it for a field. The text being edited lives in the panel (`draft`), so it survives a change of
// section, and a panel that mounts with a draft opens already editing.
const props = defineProps<{ agentId: number; draft: string | null }>()
const emit = defineEmits<{ 'update:draft': [draft: string | null] }>()
const org = useOrgStore()

const saved = ref('')
const retrying = ref(false)
// Editing and saving wait for a successful read: otherwise a save would overwrite a memory that was never seen.
const loaded = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)
const editing = ref(props.draft !== null)

const text = computed(() => props.draft ?? saved.value)
const length = computed(() => Array.from(text.value).length)
const level = computed(() => memoryLevel(length.value, MEMORY_MAX))
const over = computed(() => level.value === 'over')
const dirty = computed(() => text.value !== saved.value)
const percent = computed(() => Math.min(100, (length.value / MEMORY_MAX) * 100))
// The markdown is rendered with `html: false` (raw HTML is escaped): the text comes from the model.
const html = computed(() => renderMarkdown(saved.value))

const plural = (n: number) => `${formatCount(n)} ${n === 1 ? 'caractere' : 'caracteres'}`
const warning = computed(() => {
  const limit = formatCount(MEMORY_MAX)
  if (level.value === 'over') return `Passou do limite em ${plural(length.value - MEMORY_MAX)}: a próxima execução só lê os primeiros ${limit}.`
  if (level.value !== 'near') return null
  const left = MEMORY_MAX - length.value
  if (left === 0) return `Cheia: não sobra espaço. O que passar de ${limit} fica de fora da próxima execução.`
  return `Quase cheia: ${left === 1 ? 'sobra' : 'sobram'} ${plural(left)}. O que passar de ${limit} fica de fora da próxima execução.`
})
const TONE = {
  ok: { fill: 'bg-primary', text: 'text-fg-muted' },
  near: { fill: 'bg-secondary', text: 'text-secondary-soft' },
  over: { fill: 'bg-diff-del-fg', text: 'text-diff-del-fg' },
} as const
const tone = computed(() => TONE[level.value])

async function load(): Promise<void> {
  try {
    saved.value = (await getAgentMemory(props.agentId)).text
    loaded.value = true
    error.value = null
  } catch (e) {
    error.value = errorMessage(e)
  }
}

async function retry(): Promise<void> {
  retrying.value = true
  await load()
  retrying.value = false
}

function onInput(event: Event): void {
  const value = (event.target as HTMLTextAreaElement).value
  emit('update:draft', value === saved.value ? null : value)
}

function cancel(): void {
  editing.value = false
  error.value = null
  emit('update:draft', null)
}

async function save(): Promise<void> {
  if (!loaded.value || !dirty.value || over.value || saving.value) return
  saving.value = true
  const sent = text.value
  try {
    saved.value = (await putAgentMemory(props.agentId, sent)).text
    // What was typed while it saved stays as a draft, and keeps the field open.
    if (text.value === sent) {
      emit('update:draft', null)
      editing.value = false
    }
    error.value = null
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    saving.value = false
  }
}

onMounted(() => { void load() })
// The agent rewrites its memory during a run; the reading follows it, a draft of yours is not overwritten.
watch(() => org.changes[props.agentId], () => { void load() })
</script>

<template>
  <section aria-label="Memória do agente" class="flex min-w-0 flex-col gap-3">
    <div class="flex flex-wrap items-center gap-x-3 gap-y-2">
      <p class="m-0 min-w-48 flex-1 text-xs text-fg-subtle">O que o agente anotou para as próximas execuções. Ele reescreve este texto; você também pode.</p>
      <span
        data-test="memory-meter"
        role="meter"
        aria-label="Uso da memória"
        aria-valuemin="0"
        :aria-valuemax="MEMORY_MAX"
        :aria-valuenow="length"
        :data-level="level"
        class="h-1.5 w-28 shrink-0 overflow-hidden rounded-full bg-elevated"
      >
        <span class="block h-full" :class="tone.fill" :style="{ width: `${percent}%` }" />
      </span>
      <span data-test="memory-count" class="font-mono text-xs" :class="tone.text">{{ formatCount(length) }} de {{ formatCount(MEMORY_MAX) }}</span>
      <template v-if="editing">
        <button type="button" data-test="memory-cancel" :class="BTN_SMALL" @click="cancel">Cancelar</button>
        <button type="button" data-test="memory-save" :class="BTN_PRIMARY" :disabled="!loaded || !dirty || over || saving" @click="save">{{ saving ? 'Salvando…' : 'Salvar' }}</button>
      </template>
      <button v-else type="button" data-test="memory-edit" :class="BTN_SMALL" :disabled="!loaded" @click="editing = true">Editar</button>
    </div>
    <p v-if="warning" data-test="memory-warning" class="m-0 text-xs" :class="tone.text">{{ warning }}</p>
    <template v-if="editing">
      <textarea
        :value="text"
        data-test="memory-text"
        aria-label="Memória"
        rows="12"
        spellcheck="false"
        :disabled="!loaded"
        :class="[AREA, 'font-mono text-[0.8125rem]']"
        @input="onInput"
      />
      <span v-if="dirty" class="text-xs text-fg-subtle">Alterações não salvas</span>
    </template>
    <p v-else-if="loaded && saved === ''" data-test="memory-empty" class="m-0 rounded-xl border border-line bg-bg px-5 py-4 text-sm text-fg-muted">O agente ainda não anotou nada.</p>
    <div v-else-if="loaded && saved !== ''" data-test="memory-view" class="markdown min-w-0 rounded-xl border border-line bg-bg px-5 py-4 text-sm leading-relaxed text-fg-muted"><div v-html="html" /></div>
    <div v-if="error" class="flex flex-wrap items-center gap-3">
      <p data-test="memory-error" role="alert" :class="ERROR">{{ error }}</p>
      <button v-if="!loaded" type="button" data-test="memory-retry" :class="BTN_SMALL" :disabled="retrying" @click="retry">Tentar de novo</button>
    </div>
  </section>
</template>
