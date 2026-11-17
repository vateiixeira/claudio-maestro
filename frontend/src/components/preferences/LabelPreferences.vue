<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { errorMessage } from '../../api/http'
import { DEFAULT_LABEL_COLOR, LABEL_PALETTE, labelStyle } from '../../labelColor'
import { useLabelsStore } from '../../stores/labels'
import ConfirmDialog from '../ConfirmDialog.vue'
import { useLabelUsage } from '../labels/useLabelUsage'
import GroupHeader from '../ui/GroupHeader.vue'
import LabelPalette from '../ui/LabelPalette.vue'

const labels = useLabelsStore()
const usage = useLabelUsage()

// Names typed but not saved yet, by label id. A row without an entry follows the catalog, so a
// reload (another tab renamed the label) reaches it; a pending edit stays until it is saved or dropped.
const drafts = reactive<Record<number, string>>({})
const errors = reactive<Record<number, string>>({})
const busy = reactive<Record<number, boolean>>({})
// Edits wait here while a save of the same row is running: the newest value of each field wins.
type Change = { slug?: string; color?: string }
const queued: Record<number, Change> = {}
const inflight: Record<number, Change> = {}
// The color picked but not confirmed by the server yet; the row shows it meanwhile.
const chosen = reactive<Record<number, string>>({})
// The native picker fires on every drag step: only the last color of a pause is saved.
const COLOR_PAUSE_MS = 300
const colorTimers = new Map<number, { timer: ReturnType<typeof setTimeout>; color: string }>()
const confirming = ref<number | null>(null)
const paletteFor = ref<number | null>(null)
const inputs = new Map<number, HTMLInputElement>()

const createSlug = ref('')
const createColor = ref(LABEL_PALETTE[4] ?? DEFAULT_LABEL_COLOR)
const createError = ref('')
const creating = ref(false)

const confirmingUnused = ref(false)
const bulkBusy = ref(false)
const bulkError = ref('')

// Most used first; ties keep the catalog order (the sort is stable).
const sorted = computed(() => [...labels.labels].sort((a, b) => usage.count(b.id) - usage.count(a.id)))
const used = computed(() => sorted.value.filter((l) => usage.count(l.id) > 0))
const unused = computed(() => sorted.value.filter((l) => usage.count(l.id) === 0))

const groups = computed(() =>
  [
    { key: 'used', rows: used.value },
    { key: 'unused', rows: unused.value },
  ].filter((group) => group.rows.length > 0),
)

const draftOf = (id: number): string => drafts[id] ?? labels.byId(id)?.slug ?? ''

watch(
  () => labels.labels.map((l) => l.id),
  (ids) => {
    const present = new Set(ids)
    for (const record of [drafts, errors, busy, chosen, queued, inflight] as Record<number, unknown>[]) {
      for (const key of Object.keys(record)) if (!present.has(Number(key))) delete record[Number(key)]
    }
    for (const id of [...inputs.keys()]) if (!present.has(id)) inputs.delete(id)
    for (const id of [...colorTimers.keys()]) {
      if (present.has(id)) continue
      clearTimeout(colorTimers.get(id)?.timer)
      colorTimers.delete(id)
    }
    if (confirming.value !== null && !present.has(confirming.value)) confirming.value = null
    if (paletteFor.value !== null && !present.has(paletteFor.value)) paletteFor.value = null
  },
)
watch(
  () => unused.value.length,
  (total) => {
    if (total === 0) confirmingUnused.value = false
  },
)

function setInput(id: number, el: unknown): void {
  if (el instanceof HTMLInputElement) inputs.set(id, el)
  else inputs.delete(id)
}

function onInput(id: number, event: Event): void {
  drafts[id] = (event.target as HTMLInputElement).value
  delete errors[id]
}

function focusName(id: number): void {
  const input = inputs.get(id)
  input?.focus()
  input?.select()
}

/** Sends the edits of a row one save at a time; what arrives meanwhile is merged and sent right after. */
function enqueue(id: number, change: Change): void {
  queued[id] = { ...queued[id], ...change }
  if (!busy[id]) void drain(id)
}

async function drain(id: number): Promise<void> {
  busy[id] = true
  delete errors[id]
  try {
    while (queued[id]) {
      const wanted = queued[id]
      delete queued[id]
      const label = labels.byId(id)
      if (!label) break
      const change: Change = {}
      if (wanted.slug !== undefined && wanted.slug !== label.slug) change.slug = wanted.slug
      if (wanted.color !== undefined && wanted.color.toLowerCase() !== label.color.toLowerCase()) change.color = wanted.color
      if (change.slug !== undefined || change.color !== undefined) {
        inflight[id] = change
        try {
          await labels.update(id, change)
        } catch (e) {
          errors[id] = errorMessage(e)
        } finally {
          delete inflight[id]
        }
      }
      settle(id, wanted)
    }
  } finally {
    delete busy[id]
  }
}

/** Drops the draft of what was just sent, unless the person has typed something newer meanwhile. */
function settle(id: number, sent: Change): void {
  const draft = drafts[id]
  if (sent.slug !== undefined && draft !== undefined && draft.trim().toLowerCase() === sent.slug) delete drafts[id]
  if (sent.color !== undefined && chosen[id]?.toLowerCase() === sent.color.toLowerCase()) delete chosen[id]
}

/** Saves the typed name when it differs from the saved one (blur and Enter come here). */
function commitName(id: number): void {
  const label = labels.byId(id)
  const draft = drafts[id]
  if (!label || draft === undefined) return
  const typed = draft.trim().toLowerCase()
  // What the row is about to be: the name still waiting or being saved, else the saved one.
  const effective = queued[id]?.slug ?? inflight[id]?.slug ?? label.slug
  if (typed === effective) {
    if (typed === label.slug) delete drafts[id]
    return
  }
  if (!typed) {
    delete drafts[id]
    errors[id] = 'A etiqueta precisa de um nome.'
    return
  }
  enqueue(id, { slug: typed })
}

function onNameKeydown(id: number, event: KeyboardEvent): void {
  if (event.isComposing) return
  if (event.key === 'Enter') {
    event.preventDefault()
    commitName(id)
  } else if (event.key === 'Escape' && drafts[id] !== undefined) {
    // Closes only the edit, not the window around it.
    event.preventDefault()
    event.stopPropagation()
    delete drafts[id]
    delete errors[id]
    if (queued[id]) delete queued[id].slug
  }
}

function pickColor(id: number, color: string): void {
  chosen[id] = color
  const waiting = colorTimers.get(id)
  if (waiting) clearTimeout(waiting.timer)
  colorTimers.delete(id)
  if (LABEL_PALETTE.includes(color.toLowerCase())) {
    paletteFor.value = null
    enqueue(id, { color })
    return
  }
  // A custom color comes from the native picker, which stays open and fires while the person drags.
  const timer = setTimeout(() => {
    colorTimers.delete(id)
    enqueue(id, { color })
  }, COLOR_PAUSE_MS)
  colorTimers.set(id, { timer, color })
}

onBeforeUnmount(() => {
  for (const [id, { timer, color }] of colorTimers) {
    clearTimeout(timer)
    enqueue(id, { color })
  }
  colorTimers.clear()
})

async function remove(id: number): Promise<void> {
  busy[id] = true
  delete errors[id]
  try {
    await labels.remove(id)
    confirming.value = null
  } catch (e) {
    errors[id] = errorMessage(e)
  } finally {
    delete busy[id]
  }
}

async function removeUnused(): Promise<void> {
  const targets = [...unused.value]
  bulkBusy.value = true
  bulkError.value = ''
  // One at a time and stopping at the first failure: the ones already gone stay gone, the rest stay listed.
  try {
    for (const label of targets) {
      try {
        await labels.remove(label.id)
      } catch (e) {
        bulkError.value = `Não deu para apagar “${label.slug}”: ${errorMessage(e)}`
        break
      }
    }
  } finally {
    confirmingUnused.value = false
    bulkBusy.value = false
  }
}

async function create(): Promise<void> {
  const slug = createSlug.value.trim().toLowerCase()
  if (!slug || creating.value) return
  creating.value = true
  createError.value = ''
  try {
    await labels.create(slug, createColor.value)
    createSlug.value = ''
  } catch (e) {
    createError.value = errorMessage(e)
  } finally {
    creating.value = false
  }
}

function onCreateKeydown(event: KeyboardEvent): void {
  if (event.isComposing || event.key !== 'Enter') return
  event.preventDefault()
  void create()
}

const ROW = 'grid grid-cols-[minmax(0,1fr)_3.75rem_8rem_6rem] items-center gap-x-4'
const ICON_BUTTON =
  'inline-flex size-7 cursor-pointer items-center justify-center rounded-lg border-0 bg-transparent p-0 text-fg-subtle hover:bg-card hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-primary'
const TEXT_BUTTON =
  'h-8 cursor-pointer rounded-lg px-3 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary'
</script>

<template>
  <div class="flex flex-col gap-5 px-7 py-6">
    <p class="m-0 text-fg-muted">
      Etiquetas valem para todos os projetos. Aplique-as em cada conversa pelo painel de detalhes.
    </p>

    <div data-test="label-create-form" class="flex flex-col gap-1.5">
      <div class="flex flex-wrap items-center gap-x-2.5 gap-y-3">
        <input
          v-model="createSlug"
          data-test="label-create-slug"
          aria-label="Nome da nova etiqueta"
          placeholder="nova-etiqueta"
          maxlength="32"
          autocomplete="off"
          class="h-9 min-w-0 flex-1 basis-48 rounded-[0.625rem] border border-line-strong bg-elevated px-3 font-mono text-[0.8125rem] text-fg outline-none placeholder:text-fg-subtle focus:border-fg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          @keydown="onCreateKeydown"
        />
        <LabelPalette v-model="createColor" />
        <button
          type="button"
          data-test="label-create"
          :disabled="creating || !createSlug.trim()"
          :class="TEXT_BUTTON"
          class="border-0 bg-primary text-primary-fg hover:bg-primary-soft disabled:cursor-default disabled:opacity-50"
          @click="create"
        >Criar</button>
      </div>
      <p v-if="createError" data-test="label-error" role="alert" class="m-0 text-xs text-diff-del-fg">{{ createError }}</p>
    </div>

    <p v-if="!labels.labels.length" class="m-0 text-sm text-fg-subtle">
      Nenhuma etiqueta ainda. Crie a primeira acima.
    </p>

    <template v-else>
      <div :class="ROW" class="h-7 border-b border-line-strong font-mono text-[0.65625rem] font-semibold tracking-[0.08em] text-fg-subtle uppercase" aria-hidden="true">
        <span>Etiqueta</span>
        <span>Cor</span>
        <span>Uso</span>
        <span />
      </div>

      <div v-for="group in groups" :key="group.key" :data-test="group.key === 'unused' ? 'label-unused-group' : undefined" class="-mt-3">
        <GroupHeader v-if="group.key === 'unused'" title="Sem uso" :count="group.rows.length" class="mb-1">
          <button
            type="button"
            data-test="label-delete-unused"
            :disabled="bulkBusy"
            class="h-7 cursor-pointer rounded-lg border border-line-strong bg-transparent px-2.5 text-xs font-medium text-fg-muted hover:bg-card hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-default disabled:opacity-50"
            @click="confirmingUnused = true"
          >{{ group.rows.length === 1 ? 'Apagar a 1 sem uso' : `Apagar as ${group.rows.length} sem uso` }}</button>
        </GroupHeader>
        <p v-if="group.key === 'unused' && bulkError" data-test="label-error" role="alert" class="m-0 py-1.5 text-xs text-diff-del-fg">{{ bulkError }}</p>

        <ul class="m-0 flex list-none flex-col p-0">
          <li
            v-for="label in group.rows"
            :key="label.id"
            data-test="label-row"
            :data-slug="label.slug"
            class="flex flex-col border-b border-line text-[0.8125rem]"
          >
            <div :class="ROW" class="min-h-[2.875rem]">
              <span class="relative flex min-w-0 items-center">
                <span
                  aria-hidden="true"
                  class="pointer-events-none absolute left-2.5 size-2 rounded-full border border-fg-subtle"
                  :style="{ background: labelStyle(chosen[label.id] ?? label.color)['--label-dot'] }"
                />
                <input
                  :ref="(el) => setInput(label.id, el)"
                  :value="draftOf(label.id)"
                  data-test="label-edit-slug"
                  :aria-label="`Nome de ${label.slug}`"
                  maxlength="32"
                  autocomplete="off"
                  spellcheck="false"
                  :style="{ backgroundColor: labelStyle(chosen[label.id] ?? label.color).backgroundColor, width: `min(100%, calc(${Math.max(draftOf(label.id).length, 4)}ch + 2.75rem))` }"
                  class="h-[1.625rem] max-w-full rounded-full border border-transparent py-0 pr-3 pl-6 font-mono text-xs text-fg outline-none hover:border-line-strong focus:border-fg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                  @input="onInput(label.id, $event)"
                  @blur="commitName(label.id)"
                  @keydown="onNameKeydown(label.id, $event)"
                />
              </span>
              <span>
                <button
                  type="button"
                  data-test="label-edit-color"
                  :aria-label="`Trocar a cor de ${label.slug}`"
                  :aria-expanded="paletteFor === label.id ? 'true' : 'false'"
                  :style="{ backgroundColor: chosen[label.id] ?? label.color }"
                  class="block size-5 cursor-pointer rounded-full border-0 p-0 shadow-[0_0_0_1px_var(--color-fg-subtle)] hover:scale-110 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                  @click="paletteFor = paletteFor === label.id ? null : label.id"
                />
              </span>
              <span data-test="label-usage" :class="usage.count(label.id) === 0 ? 'text-fg-subtle' : 'text-fg-muted'">{{ usage.countText(label.id) }}</span>
              <span class="flex justify-end gap-0.5">
                <button type="button" :class="ICON_BUTTON" :aria-label="`Renomear ${label.slug}`" :title="`Renomear ${label.slug}`" @click="focusName(label.id)">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16v4zM14 6l4 4" /></svg>
                </button>
                <button
                  type="button"
                  data-test="label-delete"
                  :class="ICON_BUTTON"
                  :aria-label="`Apagar ${label.slug}`"
                  :title="`Apagar ${label.slug}`"
                  @click="confirming = label.id"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13" /></svg>
                </button>
              </span>
            </div>
            <div v-if="paletteFor === label.id" class="pb-3">
              <LabelPalette :model-value="chosen[label.id] ?? label.color" @update:model-value="pickColor(label.id, $event)" />
            </div>
            <div v-if="confirming === label.id" class="flex flex-wrap items-center gap-2 pb-3 text-sm">
              <span v-if="usage.count(label.id) > 0">Apagar “{{ label.slug }}” tira a etiqueta de {{ usage.countText(label.id) }}.</span>
              <span v-else>Apagar “{{ label.slug }}”? Nenhuma conversa usa essa etiqueta.</span>
              <button
                type="button"
                data-test="label-delete-confirm"
                :disabled="busy[label.id]"
                :class="TEXT_BUTTON"
                class="border border-diff-del-fg/45 bg-transparent text-diff-del-fg hover:bg-diff-del-bg disabled:opacity-60"
                @click="remove(label.id)"
              >Apagar mesmo</button>
              <button type="button" :class="TEXT_BUTTON" class="border border-line-strong bg-transparent font-medium text-fg hover:bg-card" @click="confirming = null">Cancelar</button>
            </div>
            <p v-if="errors[label.id]" data-test="label-error" role="alert" class="m-0 pb-2 text-xs text-diff-del-fg">{{ errors[label.id] }}</p>
          </li>
        </ul>
      </div>
    </template>

    <ConfirmDialog
      v-if="confirmingUnused"
      :title="unused.length === 1 ? 'Apagar 1 etiqueta sem uso?' : `Apagar ${unused.length} etiquetas sem uso?`"
      confirm-label="Apagar"
      tone="danger"
      :confirm-disabled="bulkBusy"
      @confirm="removeUnused"
      @cancel="confirmingUnused = false"
    >
      <p class="m-0 text-sm text-fg-muted">Nenhuma conversa usa {{ unused.length === 1 ? 'esta etiqueta' : 'estas etiquetas' }}. Não dá para desfazer.</p>
      <ul data-test="label-delete-unused-list" class="m-0 flex max-h-48 list-none flex-wrap gap-1.5 overflow-y-auto p-0">
        <li v-for="label in unused" :key="label.id" class="rounded-full bg-elevated px-2 py-0.5 font-mono text-xs break-all">{{ label.slug }}</li>
      </ul>
    </ConfirmDialog>
  </div>
</template>
