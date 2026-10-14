<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { errorMessage } from '../../api/http'
import { useLabelsStore } from '../../stores/labels'
import { useSessionsStore } from '../../stores/sessions'
import LabelBadge from '../labels/LabelBadge.vue'

const labels = useLabelsStore()
const sessions = useSessionsStore()

// Draft of each row: what the user typed, kept apart from the saved label until Salvar.
const drafts = reactive<Record<number, { slug: string; color: string }>>({})
const errors = reactive<Record<number, string>>({})
const confirming = ref<number | null>(null)
const busy = ref<number | null>(null)

function draft(id: number) {
  const label = labels.byId(id)
  // A label deleted in another tab has no row anymore; do not throw while the view catches up.
  if (!label) return drafts[id] ?? { slug: '', color: '' }
  return (drafts[id] ??= { slug: label.slug, color: label.color })
}

// What the catalog said last time. A row whose draft still equals it has no pending edit,
// so a reload (another tab renamed the label) may replace the draft; pending edits stay.
let known: Record<number, { slug: string; color: string }> = Object.fromEntries(
  labels.labels.map((l) => [l.id, { slug: l.slug, color: l.color }]),
)
watch(
  () => labels.labels.map((l) => ({ id: l.id, slug: l.slug, color: l.color })),
  (next) => {
    const present = new Set(next.map((l) => l.id))
    for (const key of Object.keys(drafts)) {
      const id = Number(key)
      if (present.has(id)) continue
      delete drafts[id]
      delete errors[id]
    }
    if (confirming.value !== null && !present.has(confirming.value)) confirming.value = null
    const updated: typeof known = {}
    for (const { id, slug, color } of next) {
      const pending = drafts[id]
      const before = known[id]
      if (pending && before && pending.slug === before.slug && pending.color === before.color) {
        drafts[id] = { slug, color }
      }
      updated[id] = { slug, color }
    }
    known = updated
  },
)

/** How many sessions of the store have the label. */
const usage = computed(() => {
  const counts: Record<number, number> = {}
  for (const list of Object.values(sessions.byProject)) {
    for (const session of list) for (const id of session.label_ids ?? []) counts[id] = (counts[id] ?? 0) + 1
  }
  return counts
})
const count = (id: number) => usage.value[id] ?? 0
const countText = (id: number) => `${count(id)} ${count(id) === 1 ? 'conversa' : 'conversas'}`

function changed(id: number): boolean {
  const label = labels.byId(id)
  if (!label) return false
  const d = draft(id)
  return d.slug.trim().toLowerCase() !== label.slug || d.color.toLowerCase() !== label.color
}

async function save(id: number) {
  if (!labels.byId(id)) return
  busy.value = id
  delete errors[id]
  try {
    const d = draft(id)
    const saved = await labels.update(id, { slug: d.slug, color: d.color })
    drafts[id] = { slug: saved.slug, color: saved.color }
  } catch (e) {
    errors[id] = errorMessage(e)
  } finally {
    busy.value = null
  }
}

async function remove(id: number) {
  busy.value = id
  delete errors[id]
  try {
    await labels.remove(id)
    confirming.value = null
  } catch (e) {
    errors[id] = errorMessage(e)
  } finally {
    busy.value = null
  }
}
</script>

<template>
  <div class="flex flex-col gap-4 px-7 py-6">
    <p class="m-0 text-fg-muted">
      Etiquetas valem para todos os projetos. Aplique-as em cada conversa pelo painel de detalhes.
    </p>
    <p v-if="!labels.labels.length" class="m-0 text-sm text-fg-subtle">
      Nenhuma etiqueta ainda. Crie a primeira no painel de detalhes de uma conversa, em Etiquetas → Editar.
    </p>
    <ul v-else class="m-0 flex list-none flex-col gap-2 p-0">
      <li
        v-for="label in labels.labels"
        :key="label.id"
        data-test="label-row"
        :data-slug="label.slug"
        class="flex flex-col gap-1.5 rounded-lg border border-line p-3"
      >
        <div class="flex flex-wrap items-center gap-2">
          <LabelBadge :label="{ ...label, slug: draft(label.id).slug || label.slug, color: draft(label.id).color }" />
          <input
            v-model="draft(label.id).color"
            type="color"
            data-test="label-edit-color"
            :aria-label="`Cor de ${label.slug}`"
            class="size-8 cursor-pointer rounded-md border border-line-strong bg-elevated p-0.5"
          />
          <input
            v-model="draft(label.id).slug"
            data-test="label-edit-slug"
            :aria-label="`Slug de ${label.slug}`"
            maxlength="32"
            class="h-8 min-w-0 grow rounded-md border border-line-strong bg-elevated px-2 font-mono text-xs text-fg outline-none focus:border-fg-muted"
          />
          <span class="shrink-0 text-xs text-fg-subtle">{{ countText(label.id) }}</span>
          <button
            type="button"
            data-test="label-save"
            :aria-label="`Salvar ${label.slug}`"
            :disabled="busy === label.id || !changed(label.id)"
            class="h-8 rounded-md bg-primary px-3 text-sm font-semibold text-primary-fg disabled:opacity-60"
            @click="save(label.id)"
          >Salvar</button>
          <button
            type="button"
            data-test="label-delete"
            :aria-label="`Apagar ${label.slug}`"
            class="h-8 rounded-md border border-line-strong px-3 text-sm text-fg-muted hover:text-fg"
            @click="confirming = label.id"
          >Apagar</button>
        </div>
        <div v-if="confirming === label.id" class="flex flex-wrap items-center gap-2 text-sm">
          <span>Apagar “{{ label.slug }}” tira a etiqueta de {{ countText(label.id) }}.</span>
          <button
            type="button"
            data-test="label-delete-confirm"
            :disabled="busy === label.id"
            class="h-8 rounded-md bg-secondary px-3 text-sm font-semibold text-secondary-fg disabled:opacity-60"
            @click="remove(label.id)"
          >Apagar mesmo</button>
          <button type="button" class="h-8 rounded-md border border-line-strong px-3 text-sm" @click="confirming = null">Cancelar</button>
        </div>
        <p v-if="errors[label.id]" data-test="label-error" role="alert" class="m-0 text-xs text-diff-del-fg">{{ errors[label.id] }}</p>
      </li>
    </ul>
  </div>
</template>
