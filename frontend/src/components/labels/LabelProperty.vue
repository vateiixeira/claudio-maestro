<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { errorMessage } from '../../api/http'
import { LABEL_PALETTE, labelStyle } from '../../labelColor'
import { useLabelsStore } from '../../stores/labels'
import { useSessionsStore } from '../../stores/sessions'
import type { Label } from '../../types/api'
import IconCheck from '../icons/IconCheck.vue'
import IconClose from '../icons/IconClose.vue'
import IconPlus from '../icons/IconPlus.vue'
import LabelPalette from '../ui/LabelPalette.vue'
import LabelBadge from './LabelBadge.vue'
import LabelBadges from './LabelBadges.vue'
import { useLabelUsage } from './useLabelUsage'

const props = defineProps<{ sessionId: string }>()

const labels = useLabelsStore()
const sessions = useSessionsStore()
const usage = useLabelUsage()

const selected = computed(() => sessions.find(props.sessionId)?.label_ids ?? [])
const selectedLabels = computed(() =>
  selected.value.map((id) => labels.byId(id)).filter((label): label is Label => label !== undefined),
)
const open = ref(false)
const busy = ref(false)
const error = ref<string | null>(null)
const query = ref('')
const color = ref(LABEL_PALETTE[0])
// Index of the highlighted row: the options first, then the "Criar etiqueta" row. -1 is none.
const active = ref(-1)

const root = ref<HTMLElement | null>(null)
const input = ref<HTMLInputElement | null>(null)
const toggleButton = ref<HTMLButtonElement | null>(null)

const panelId = computed(() => `labels-panel-${props.sessionId}`)
const listId = computed(() => `labels-list-${props.sessionId}`)
const optionId = (id: number) => `labels-opt-${props.sessionId}-${id}`
const createId = computed(() => `labels-create-${props.sessionId}`)

const term = computed(() => query.value.trim().toLowerCase())
const options = computed(() => labels.labels.filter((l) => l.slug.includes(term.value)))
const canCreate = computed(() => term.value !== '' && !labels.labels.some((l) => l.slug === term.value))
const rowCount = computed(() => options.value.length + (canCreate.value ? 1 : 0))
const activeId = computed(() => {
  if (active.value < 0) return undefined
  const label = options.value[active.value]
  if (label) return optionId(label.id)
  return canCreate.value && active.value === options.value.length ? createId.value : undefined
})

watch(query, () => {
  active.value = -1
})
// A label deleted elsewhere or a shorter list must not leave the highlight past the end.
watch(rowCount, (count) => {
  if (active.value >= count) active.value = count - 1
})
watch(active, async () => {
  await nextTick()
  const el = activeId.value ? root.value?.querySelector<HTMLElement>(`#${activeId.value}`) : null
  el?.scrollIntoView?.({ block: 'nearest' })
})

/** The slug split around the first match of the typed text, for the `<mark>`. */
function parts(slug: string): { before: string; match: string; after: string } | null {
  const at = term.value ? slug.indexOf(term.value) : -1
  if (at < 0) return null
  return { before: slug.slice(0, at), match: slug.slice(at, at + term.value.length), after: slug.slice(at + term.value.length) }
}

async function openPanel() {
  open.value = true
  await nextTick()
  input.value?.focus()
}

function close(focusToggle: boolean) {
  open.value = false
  query.value = ''
  active.value = -1
  if (focusToggle) void nextTick(() => toggleButton.value?.focus())
}

function onToggle() {
  if (open.value) close(false)
  else void openPanel()
}

// Focus moving between the field, the chips and the palette keeps the panel open; leaving closes it.
function onFocusOut(event: FocusEvent) {
  if (!open.value) return
  const next = event.relatedTarget as Node | null
  if (next && root.value?.contains(next)) return
  close(false)
}

async function run(call: () => Promise<void>): Promise<boolean> {
  busy.value = true
  error.value = null
  try {
    await call()
    return true
  } catch (e) {
    error.value = errorMessage(e)
    return false
  } finally {
    busy.value = false
  }
}

// While a request runs the controls stay enabled (a control that turns `disabled` loses the keyboard
// focus). Changes made in that window are ignored instead. The chips and the check marks come from the
// saved state, so a failed save leaves them as they were.
async function toggle(id: number) {
  if (busy.value) return
  const next = selected.value.includes(id) ? selected.value.filter((x) => x !== id) : [...selected.value, id]
  await run(() => sessions.setLabels(props.sessionId, next))
}

async function removeChip(id: number) {
  await toggle(id)
  input.value?.focus()
}

async function createAndApply() {
  const name = query.value.trim()
  if (busy.value || !name || !canCreate.value) return
  busy.value = true
  error.value = null
  try {
    const sentColor = color.value
    const label = await labels.create(name, sentColor)
    // The label exists from here on: clear the field so sending it again does not collide.
    // A field edited while the request ran keeps what the person typed.
    if (query.value.trim() === name) query.value = ''
    if (color.value === sentColor) color.value = LABEL_PALETTE[0]
    try {
      await sessions.setLabels(props.sessionId, [...selected.value, label.id])
    } catch (e) {
      error.value = `A etiqueta “${label.slug}” foi criada, mas não foi aplicada a esta conversa. ${errorMessage(e)} Marque-a na lista.`
    }
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    busy.value = false
  }
}

// A mousedown on the empty area or on a chip would move the focus off the input, and the focus leaving
// closes the panel before the click arrives. Cancel it there; the input itself keeps its normal behavior.
function keepInputFocus(event: MouseEvent) {
  if (event.target !== input.value) event.preventDefault()
}

function onKeydown(event: KeyboardEvent) {
  const total = rowCount.value
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    if (!total) return
    const step = event.key === 'ArrowDown' ? 1 : -1
    if (active.value < 0) active.value = step === 1 ? 0 : total - 1
    else active.value = (active.value + step + total) % total
  } else if (event.key === 'Enter') {
    event.preventDefault()
    const label = options.value[active.value]
    if (label) void toggle(label.id)
    else if (canCreate.value) void createAndApply()
  }
}
</script>

<template>
  <dt class="text-fg-muted">Etiquetas</dt>
  <dd
    ref="root"
    data-test="prop-labels"
    :aria-busy="busy ? 'true' : undefined"
    class="m-0 flex min-w-0 flex-col gap-1.5"
    @focusout="onFocusOut"
  >
    <span class="flex min-w-0 flex-wrap items-center gap-1.5">
      <template v-if="!open">
        <LabelBadges v-if="selected.length" :ids="selected" :max="selected.length" />
        <span v-else class="text-fg-muted">Nenhuma</span>
      </template>
      <button
        ref="toggleButton"
        type="button"
        data-test="label-toggle"
        :aria-expanded="open"
        :aria-controls="open ? panelId : undefined"
        class="h-6 rounded-md border border-line-strong px-2 text-xs text-fg-muted hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
        @mousedown.prevent
        @click="onToggle"
      >{{ open ? 'Fechar' : 'Editar' }}</button>
    </span>

    <div v-if="open" :id="panelId" class="flex flex-col gap-1.5" @keydown.esc.stop="close(true)">
      <div
        data-test="label-field"
        class="flex min-h-11 flex-wrap items-center gap-1.5 rounded-[0.625rem] border border-line-strong bg-elevated px-2 py-1.5 focus-within:border-fg-muted"
        @mousedown="keepInputFocus"
        @click="input?.focus()"
      >
        <span
          v-for="label in selectedLabels"
          :key="label.id"
          data-test="label-chip"
          :data-slug="label.slug"
          :style="labelStyle(label.color)"
          class="inline-flex h-6.5 max-w-full items-center gap-1.5 rounded-full pr-1 pl-2.5 font-mono text-xs"
        >
          <span aria-hidden="true" class="size-2 shrink-0 rounded-full border border-fg-subtle" style="background: var(--label-dot)" />
          <span class="min-w-0 truncate" :title="label.slug">{{ label.slug }}</span>
          <button
            type="button"
            data-test="label-chip-remove"
            :aria-label="`Tirar a etiqueta ${label.slug}`"
            class="flex size-4.5 shrink-0 items-center justify-center rounded-full text-fg-muted hover:bg-line-strong hover:text-fg focus-visible:outline-2 focus-visible:outline-primary"
            @mousedown.prevent
            @click.stop="removeChip(label.id)"
          ><IconClose :size="10" /></button>
        </span>
        <input
          ref="input"
          v-model="query"
          type="text"
          data-test="label-search"
          role="combobox"
          aria-label="Procurar ou criar etiqueta"
          aria-autocomplete="list"
          aria-expanded="true"
          :aria-controls="listId"
          :aria-activedescendant="activeId"
          placeholder="Procurar ou criar…"
          autocomplete="off"
          maxlength="32"
          class="h-7 min-w-30 flex-1 border-0 bg-transparent px-1 text-sm text-fg outline-none placeholder:text-fg-muted"
          @keydown="onKeydown"
        />
      </div>

      <div class="rounded-xl border border-line bg-card p-1.5 shadow-lg" @mousedown.prevent>
        <p v-if="!labels.labels.length" class="m-0 px-2.5 py-2 text-xs text-fg-muted">Nenhuma etiqueta criada ainda.</p>
        <div :id="listId" role="listbox" aria-label="Etiquetas" aria-multiselectable="true" class="scroll-thin flex max-h-64 flex-col overflow-y-auto">
          <div
            v-for="(label, index) in options"
            :id="optionId(label.id)"
            :key="label.id"
            role="option"
            data-test="label-option"
            :data-slug="label.slug"
            :data-active="active === index ? 'true' : undefined"
            :aria-selected="selected.includes(label.id) ? 'true' : 'false'"
            class="flex h-9 shrink-0 cursor-pointer items-center gap-2.5 rounded-lg px-2.5 hover:bg-elevated data-active:bg-elevated"
            @click="toggle(label.id)"
          >
            <span
              :style="labelStyle(label.color)"
              class="inline-flex h-6.5 min-w-0 items-center gap-1.5 rounded-full px-2.5 font-mono text-xs"
            >
              <span aria-hidden="true" class="size-2 shrink-0 rounded-full border border-fg-subtle" style="background: var(--label-dot)" />
              <span class="min-w-0 truncate" :class="term ? 'text-fg-muted' : 'text-fg'">
                <template v-if="parts(label.slug)">{{ parts(label.slug)!.before }}<mark class="bg-transparent font-medium text-fg underline underline-offset-[3px]">{{ parts(label.slug)!.match }}</mark>{{ parts(label.slug)!.after }}</template>
                <template v-else>{{ label.slug }}</template>
              </span>
            </span>
            <span class="flex-1" />
            <span data-test="label-count" class="shrink-0 text-xs text-fg-subtle">{{ usage.countText(label.id) }}</span>
            <span class="flex w-4 shrink-0 justify-center text-primary" aria-hidden="true">
              <IconCheck v-if="selected.includes(label.id)" :size="14" />
            </span>
          </div>
          <template v-if="canCreate">
            <div v-if="options.length" class="mx-1 my-1.5 h-px bg-line" aria-hidden="true" />
            <div
              :id="createId"
              role="option"
              aria-selected="false"
              data-test="label-new-save"
              :data-active="active === options.length ? 'true' : undefined"
              :aria-disabled="busy ? 'true' : undefined"
              class="flex shrink-0 cursor-pointer items-center gap-2.5 rounded-t-lg bg-elevated px-2.5 py-2.5"
              @click="createAndApply"
            >
              <IconPlus :size="14" class="shrink-0 text-primary" />
              <span class="text-sm">Criar etiqueta</span>
              <LabelBadge :label="{ id: 0, slug: query.trim(), color, created_at: 0 }" />
              <span class="flex-1" />
              <kbd class="rounded-[5px] border border-line-strong px-1.5 font-mono text-[0.6875rem] text-fg-muted">Enter</kbd>
            </div>
          </template>
        </div>
        <div v-if="canCreate" class="flex items-center gap-2.5 rounded-b-lg bg-elevated px-2.5 pt-0 pb-2.5 pl-9">
          <span class="text-xs text-fg-muted">Cor</span>
          <LabelPalette v-model="color" data-test="label-new-color" />
        </div>
        <p class="m-0 mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line px-2.5 pt-2 pb-1 text-[0.6875rem] text-fg-subtle">
          <span><kbd class="rounded-[5px] border border-line-strong px-1.5 font-mono text-fg-muted">↑↓</kbd> navegar</span>
          <span><kbd class="rounded-[5px] border border-line-strong px-1.5 font-mono text-fg-muted">Enter</kbd> {{ canCreate && active < 0 ? 'cria e marca' : 'marca' }}</span>
          <span><kbd class="rounded-[5px] border border-line-strong px-1.5 font-mono text-fg-muted">Esc</kbd> fecha</span>
        </p>
      </div>
      <p v-if="error" data-test="label-error" role="alert" class="m-0 text-xs text-diff-del-fg">{{ error }}</p>
    </div>
  </dd>
</template>
