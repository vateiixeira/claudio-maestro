<script setup lang="ts">
import { ref } from 'vue'
import { BTN, FIELD } from './styles'

const props = defineProps<{
  label: string
  /** `outward` or `always`: part of the `data-test` of each piece. */
  kind: string
  /** The factory patterns: always in force, never removable. */
  defaults: readonly string[]
  /** The ones the person added. */
  custom: string[]
  placeholder: string
  save: (list: string[]) => Promise<boolean>
}>()

const draft = ref('')
const busy = ref(false)

async function add(): Promise<void> {
  const value = draft.value.trim()
  if (!value || busy.value) return
  if (props.defaults.includes(value) || props.custom.includes(value)) {
    draft.value = ''
    return
  }
  busy.value = true
  try {
    if (await props.save([...props.custom, value])) draft.value = ''
  } finally {
    busy.value = false
  }
}

async function remove(pattern: string): Promise<void> {
  if (busy.value) return
  busy.value = true
  try {
    await props.save(props.custom.filter((p) => p !== pattern))
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="flex flex-col gap-1.5">
    <h4 class="m-0 text-sm font-medium text-fg">{{ label }}</h4>
    <slot name="hint" />
    <ul class="m-0 flex list-none flex-wrap gap-1.5 p-0">
      <li v-for="pattern in defaults" :key="`d-${pattern}`" :data-test="`${kind}-default`" class="rounded-md border border-line bg-surface px-2 py-0.5 font-mono text-xs break-all text-fg-muted" title="Padrão de fábrica">{{ pattern }}</li>
      <li v-for="pattern in custom" :key="`c-${pattern}`" :data-test="`${kind}-custom`" class="flex items-center gap-1 rounded-md border border-line-strong bg-card py-0.5 pr-0.5 pl-2 min-w-0 font-mono text-xs text-fg">
        <span class="min-w-0 break-all">{{ pattern }}</span>
        <button type="button" data-test="pattern-remove" :aria-label="`Remover ${pattern}`" class="flex size-5 shrink-0 items-center justify-center rounded text-fg-subtle hover:bg-elevated hover:text-fg focus-visible:outline-2 focus-visible:outline-primary" :disabled="busy" @click="remove(pattern)">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
        </button>
      </li>
    </ul>
    <form class="flex gap-2" @submit.prevent="add">
      <input v-model="draft" :data-test="`${kind}-input`" type="text" :aria-label="`Acrescentar a: ${label}`" :placeholder="placeholder" autocomplete="off" spellcheck="false" :class="[FIELD, 'min-w-0 grow font-mono text-[0.8125rem]']" />
      <button type="button" :data-test="`${kind}-add`" :class="BTN" :disabled="busy" @click="add">Acrescentar</button>
    </form>
  </div>
</template>
