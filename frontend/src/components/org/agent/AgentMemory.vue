<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { errorMessage, getAgentMemory, putAgentMemory } from '../../../api/http'
import { MEMORY_MAX } from '../../../org'
import { useOrgStore } from '../../../stores/org'
import { AREA, BTN_PRIMARY, ERROR } from '../styles'
import { formatCount } from './helpers'

// What the agent remembers between runs: a free text it rewrites and you can edit too. The text being edited lives in
// the panel (`draft`), so it survives a change of section.
const props = defineProps<{ agentId: number; draft: string | null }>()
const emit = defineEmits<{ 'update:draft': [draft: string | null] }>()
const org = useOrgStore()

const saved = ref('')
const loading = ref(true)
const saving = ref(false)
const error = ref<string | null>(null)

const text = computed(() => props.draft ?? saved.value)
const length = computed(() => Array.from(text.value).length)
const over = computed(() => length.value > MEMORY_MAX)
const dirty = computed(() => text.value !== saved.value)

async function load(): Promise<void> {
  try {
    saved.value = (await getAgentMemory(props.agentId)).text
    error.value = null
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

function onInput(event: Event): void {
  const value = (event.target as HTMLTextAreaElement).value
  emit('update:draft', value === saved.value ? null : value)
}

async function save(): Promise<void> {
  if (!dirty.value || over.value || saving.value) return
  saving.value = true
  const sent = text.value
  try {
    saved.value = (await putAgentMemory(props.agentId, sent)).text
    // What was typed while it saved stays as a draft.
    if (text.value === sent) emit('update:draft', null)
    error.value = null
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    saving.value = false
  }
}

onMounted(() => { void load() })
// The agent rewrites its memory during a run; a draft of yours is not overwritten.
watch(() => org.changes[props.agentId], () => { void load() })
</script>

<template>
  <section aria-label="Memória do agente" class="flex min-w-0 flex-col gap-3">
    <p class="m-0 max-w-prose text-xs text-fg-subtle">O que o agente anotou para as próximas execuções. Ele reescreve este texto; você também pode.</p>
    <textarea
      :value="text"
      data-test="memory-text"
      aria-label="Memória"
      rows="12"
      spellcheck="false"
      :disabled="loading"
      :class="[AREA, 'font-mono text-[0.8125rem]']"
      @input="onInput"
    />
    <div class="flex flex-wrap items-center gap-3">
      <button type="button" data-test="memory-save" :class="BTN_PRIMARY" :disabled="!dirty || over || saving" @click="save">{{ saving ? 'Salvando…' : 'Salvar' }}</button>
      <span data-test="memory-count" class="font-mono text-xs" :class="over ? 'text-diff-del-fg' : 'text-fg-subtle'">{{ formatCount(length) }} / {{ formatCount(MEMORY_MAX) }}</span>
      <span v-if="dirty" class="text-xs text-fg-subtle">Alterações não salvas</span>
    </div>
    <p v-if="error" data-test="memory-error" role="alert" :class="ERROR">{{ error }}</p>
  </section>
</template>
