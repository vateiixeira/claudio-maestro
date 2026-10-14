<script setup lang="ts">
import { computed, ref } from 'vue'
import { errorMessage } from '../../api/http'
import { DEFAULT_LABEL_COLOR as DEFAULT_COLOR } from '../../labelColor'
import { useLabelsStore } from '../../stores/labels'
import { useSessionsStore } from '../../stores/sessions'
import LabelBadges from './LabelBadges.vue'

const props = defineProps<{ sessionId: string }>()

const labels = useLabelsStore()
const sessions = useSessionsStore()

const selected = computed(() => sessions.find(props.sessionId)?.label_ids ?? [])
const open = ref(false)
const busy = ref(false)
const error = ref<string | null>(null)
const slug = ref('')
const color = ref(DEFAULT_COLOR)

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
// focus). Changes made in that window are ignored instead.
async function toggle(id: number, event: Event) {
  const target = event.target as HTMLInputElement
  if (busy.value) {
    target.checked = selected.value.includes(id)
    return
  }
  const next = target.checked ? [...selected.value, id] : selected.value.filter((x) => x !== id)
  const ok = await run(() => sessions.setLabels(props.sessionId, next))
  // Vue does not repatch :checked when the saved state did not change: put the box back by hand.
  if (!ok) target.checked = selected.value.includes(id)
}

async function createAndApply() {
  if (busy.value || !slug.value.trim()) return
  busy.value = true
  error.value = null
  try {
    const label = await labels.create(slug.value, color.value)
    // The label exists from here on: clear the form so sending it again does not collide.
    slug.value = ''
    color.value = DEFAULT_COLOR
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
</script>

<template>
  <dt class="text-fg-muted">Etiquetas</dt>
  <dd data-test="prop-labels" :aria-busy="busy ? 'true' : undefined" class="m-0 flex min-w-0 flex-col gap-1.5">
    <span class="flex min-w-0 flex-wrap items-center gap-1.5">
      <LabelBadges v-if="selected.length" :ids="selected" :max="selected.length" />
      <span v-else class="text-fg-muted">Nenhuma</span>
      <button
        type="button"
        data-test="label-toggle"
        :aria-expanded="open"
        :aria-controls="open ? `labels-panel-${sessionId}` : undefined"
        class="h-6 rounded-md border border-line-strong px-2 text-xs text-fg-muted hover:text-fg"
        @click="open = !open"
      >{{ open ? 'Fechar' : 'Editar' }}</button>
    </span>
    <div v-if="open" :id="`labels-panel-${sessionId}`" class="flex flex-col gap-1.5 rounded-md border border-line bg-elevated p-2">
      <p v-if="!labels.labels.length" class="m-0 text-xs text-fg-muted">Nenhuma etiqueta criada ainda.</p>
      <label
        v-for="label in labels.labels"
        :key="label.id"
        data-test="label-option"
        :data-slug="label.slug"
        class="flex items-center gap-2 text-sm"
      >
        <input
          type="checkbox"
          :checked="selected.includes(label.id)"
          @change="toggle(label.id, $event)"
        />
        <span class="size-2.5 shrink-0 rounded-[3px]" :style="{ backgroundColor: label.color }" aria-hidden="true" />
        <span class="min-w-0 truncate font-mono text-xs">{{ label.slug }}</span>
      </label>
      <form class="flex items-center gap-1.5 border-t border-line pt-2" @submit.prevent="createAndApply">
        <input
          v-model="color"
          type="color"
          data-test="label-new-color"
          aria-label="Cor da nova etiqueta"
          class="size-8 shrink-0 cursor-pointer rounded-md border border-line-strong bg-elevated p-0.5"
        />
        <input
          v-model="slug"
          data-test="label-new-slug"
          aria-label="Slug da nova etiqueta"
          placeholder="nova-etiqueta"
          maxlength="32"
          class="h-8 min-w-0 grow rounded-md border border-line-strong bg-elevated px-2 font-mono text-xs text-fg outline-none focus:border-fg-muted"
        />
        <button
          type="submit"
          data-test="label-new-save"
          :disabled="!slug.trim()"
          :aria-disabled="busy ? 'true' : undefined"
          class="h-8 shrink-0 rounded-md bg-primary px-2.5 text-xs font-semibold text-primary-fg disabled:opacity-60 aria-disabled:opacity-60"
        >Criar</button>
      </form>
      <p v-if="error" data-test="label-error" role="alert" class="m-0 text-xs text-diff-del-fg">{{ error }}</p>
    </div>
  </dd>
</template>
