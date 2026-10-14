<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId } from 'vue'

const props = withDefaults(
  defineProps<{ title: string; confirmLabel: string; tone?: 'danger' | 'warn' | 'primary'; confirmDisabled?: boolean; autofocus?: boolean }>(),
  { tone: 'primary', confirmDisabled: false, autofocus: true },
)
const emit = defineEmits<{ confirm: []; cancel: [] }>()

const titleId = useId()
const panel = ref<HTMLElement | null>(null)
const cancelButton = ref<HTMLButtonElement | null>(null)
let previous: HTMLElement | null = null

onMounted(async () => {
  previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
  // On the document, not on the panel: a click on the text sends focus to the body, and Esc and Tab must still work.
  document.addEventListener('keydown', onKeydown)
  await nextTick()
  if (props.autofocus) cancelButton.value?.focus()
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
  previous?.focus()
})

const confirmClass = computed(() => ({
  danger: 'border border-diff-del-fg/45 bg-transparent text-diff-del-fg hover:bg-diff-del-bg',
  warn: 'border-0 bg-secondary text-secondary-fg hover:bg-secondary-soft',
  primary: 'border-0 bg-primary text-primary-fg hover:bg-primary-soft',
})[props.tone])

// Keeps Tab inside the dialog.
function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.preventDefault()
    emit('cancel')
    return
  }
  if (event.key !== 'Tab' || !panel.value) return
  const items = [...panel.value.querySelectorAll<HTMLElement>('button:not([disabled]), input, textarea, [tabindex]:not([tabindex="-1"])')]
  if (items.length === 0) return
  const first = items[0]
  const last = items[items.length - 1]
  if (!panel.value.contains(document.activeElement)) {
    event.preventDefault()
    ;(event.shiftKey ? last : first).focus()
  } else if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" @click.self="emit('cancel')">
    <section
      ref="panel"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="titleId"
      class="flex w-full max-w-[480px] flex-col gap-3.5 rounded-2xl border bg-panel p-5 shadow-2xl"
      :class="tone === 'warn' ? 'border-secondary/50' : 'border-line-strong'"
    >
      <h2 :id="titleId" class="m-0 text-[1.0625rem] font-semibold tracking-[-0.015em] break-words">{{ title }}</h2>
      <slot />
      <div class="flex justify-end gap-2">
        <button ref="cancelButton" type="button" data-test="confirm-cancel" class="h-9 rounded-lg border border-line-strong px-3.5 text-sm font-medium text-fg hover:bg-card focus-visible:outline-2 focus-visible:outline-primary" @click="emit('cancel')">Cancelar</button>
        <button type="button" data-test="confirm-ok" :disabled="confirmDisabled" class="h-9 rounded-lg px-3.5 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-default disabled:opacity-50" :class="confirmClass" @click="emit('confirm')">{{ confirmLabel }}</button>
      </div>
    </section>
  </div>
</template>
