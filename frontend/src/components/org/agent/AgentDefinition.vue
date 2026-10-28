<script setup lang="ts">
import { computed, onMounted, ref, useId, watch } from 'vue'
import { ApiError, DefinitionInvalidError, errorMessage, getAgentDefinition, putAgentDefinition } from '../../../api/http'
import { DEFINITION_MAX_BYTES } from '../../../org'
import { useOrgStore } from '../../../stores/org'
import { BTN, BTN_PRIMARY, BTN_SMALL, ERROR } from '../styles'
import { byteLength, DEFINITION_FIELDS, formatCount, type DefinitionDraft } from './helpers'

// The editor of the AGENT.md. The text being edited lives in the panel (`draft`), so it survives a change of section;
// the file on disk and its hash are read here.
const props = defineProps<{ agentId: number; draft: DefinitionDraft | null }>()
const emit = defineEmits<{ 'update:draft': [draft: DefinitionDraft | null] }>()
const org = useOrgStore()

const CONFLICT_TEXT = 'O arquivo mudou fora daqui. Recarregue para ver a versão atual.'

const saved = ref('')
const fileHash = ref<string | null>(null)
const loading = ref(true)
const loadError = ref<string | null>(null)
const saving = ref(false)
const saveError = ref<{ message: string; line: number | null } | null>(null)
const conflict = ref(false)
const area = ref<HTMLTextAreaElement | null>(null)
const helpId = useId()
const errorId = useId()

const text = computed(() => props.draft?.text ?? saved.value)
// The hash the text being edited is based on: the one the draft was started from, or the file's.
const baseHash = computed(() => props.draft?.hash ?? fileHash.value)
const bytes = computed(() => byteLength(text.value))
const over = computed(() => bytes.value > DEFINITION_MAX_BYTES)
const dirty = computed(() => text.value !== saved.value)
const stale = computed(() => props.draft !== null && props.draft.hash !== fileHash.value)
const agent = computed(() => org.byId(props.agentId))
const problem = computed(() => saveError.value ?? (conflict.value || stale.value ? { message: CONFLICT_TEXT, line: null } : null))

async function load(options: { quiet?: boolean } = {}): Promise<void> {
  try {
    const file = await getAgentDefinition(props.agentId)
    saved.value = file.text
    fileHash.value = file.hash
    loadError.value = null
  } catch (e) {
    // A quiet reread (after an event) keeps what the screen has.
    if (!options.quiet) loadError.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

/** Throws the draft away and shows the file as it is now. */
async function reload(): Promise<void> {
  saveError.value = null
  conflict.value = false
  await load()
  if (loadError.value === null) emit('update:draft', null)
}

function onInput(event: Event): void {
  const value = (event.target as HTMLTextAreaElement).value
  emit('update:draft', value === saved.value ? null : { text: value, hash: baseHash.value })
}

async function save(): Promise<void> {
  if (!dirty.value || over.value || saving.value) return
  saving.value = true
  saveError.value = null
  conflict.value = false
  const sent = text.value
  try {
    const file = await putAgentDefinition(props.agentId, { text: sent, hash: baseHash.value })
    saved.value = file.text
    fileHash.value = file.hash
    // What was typed while it saved stays as a draft, based on the file just written.
    emit('update:draft', text.value === sent ? null : { text: text.value, hash: file.hash })
    // The name, the description and the model come from the file.
    void org.load()
  } catch (e) {
    if (e instanceof DefinitionInvalidError) saveError.value = { message: e.message, line: e.line }
    else if (e instanceof ApiError && e.status === 409) conflict.value = true
    else saveError.value = { message: errorMessage(e), line: null }
  } finally {
    saving.value = false
  }
}

/** Puts the cursor on the line the error points to. */
function goToLine(line: number): void {
  const el = area.value
  if (!el) return
  const lines = el.value.split('\n')
  const start = lines.slice(0, line - 1).reduce((sum, l) => sum + l.length + 1, 0)
  const end = start + (lines[line - 1]?.length ?? 0)
  el.focus()
  el.setSelectionRange(start, end)
}

onMounted(() => { void load() })
watch(() => org.changes[props.agentId], () => { void load({ quiet: true }) })
</script>

<template>
  <section aria-label="Definição do agente" class="flex min-w-0 flex-col gap-3">
    <p v-if="agent?.definition_error" data-test="definition-current-error" role="alert" :class="ERROR">
      O AGENT.md não abre: {{ agent.definition_error }}
    </p>

    <div :id="helpId" data-test="definition-help" class="flex flex-col gap-1.5 text-xs text-fg-muted">
      <p class="m-0">
        O arquivo começa com um cabeçalho entre duas linhas <code class="font-mono">---</code>; o resto é o prompt do agente.
      </p>
      <ul class="m-0 flex list-none flex-col gap-0.5 p-0">
        <li v-for="field in DEFINITION_FIELDS" :key="field.key"><code class="font-mono text-fg">{{ field.key }}</code>: {{ field.help }}</li>
      </ul>
    </div>

    <p v-if="loading" role="status" class="m-0 text-sm text-fg-subtle">Carregando o AGENT.md…</p>
    <div v-else-if="loadError && !draft" class="flex flex-wrap items-center gap-3">
      <p data-test="definition-load-error" role="alert" :class="ERROR">{{ loadError }}</p>
      <button type="button" :class="BTN" @click="load()">Tentar de novo</button>
    </div>
    <template v-else>
      <textarea
        ref="area"
        :value="text"
        data-test="definition-text"
        aria-label="AGENT.md"
        :aria-describedby="[helpId, problem ? errorId : ''].join(' ').trim()"
        :aria-invalid="problem ? 'true' : undefined"
        rows="22"
        spellcheck="false"
        class="min-h-72 w-full resize-y rounded-lg border border-line-strong bg-surface p-2.5 font-mono text-[0.8125rem] leading-relaxed text-fg focus-visible:outline-2 focus-visible:outline-primary"
        @input="onInput"
      />
      <div v-if="problem" :id="errorId" data-test="definition-error" role="alert" class="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm text-diff-del-fg">
        <span>{{ problem.message }}<template v-if="problem.line"> (linha {{ problem.line }})</template></span>
        <button v-if="problem.line" type="button" data-test="definition-goto" :class="BTN_SMALL" @click="goToLine(problem.line)">Ir para a linha {{ problem.line }}</button>
        <button v-if="conflict || stale" type="button" data-test="definition-reload" :class="BTN_SMALL" @click="reload">Recarregar</button>
      </div>
      <div class="flex flex-wrap items-center gap-3">
        <button type="button" data-test="definition-save" :class="BTN_PRIMARY" :disabled="!dirty || over || saving" @click="save">{{ saving ? 'Salvando…' : 'Salvar' }}</button>
        <span data-test="definition-count" class="font-mono text-xs" :class="over ? 'text-diff-del-fg' : 'text-fg-subtle'">{{ formatCount(bytes) }} / {{ formatCount(DEFINITION_MAX_BYTES) }} bytes</span>
        <span v-if="dirty" class="text-xs text-fg-subtle">Alterações não salvas</span>
      </div>
    </template>
  </section>
</template>
