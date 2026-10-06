<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'

// "Sem perguntas" runs every tool without asking, so choosing it always needs an explicit confirmation.
// Render it with `v-if`: it takes the focus when it appears and gives it back to the previous element when it goes.
const emit = defineEmits<{ confirm: []; cancel: [] }>()

const confirmButton = ref<HTMLButtonElement | null>(null)
const cancelButton = ref<HTMLButtonElement | null>(null)
const returnFocusTo = document.activeElement as HTMLElement | null

// The dangerous button is never the default: Enter right after opening must not activate it.
onMounted(() => cancelButton.value?.focus())
onUnmounted(() => returnFocusTo?.focus())

// Keeps Tab and Shift+Tab between the two buttons while the dialog is open. Every key stops here, so a
// dialog around this one (the new conversation window) does not react to the Escape or the Tab.
function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    emit('cancel')
  } else if (event.key === 'Tab') {
    event.preventDefault()
    event.stopPropagation()
    // Two buttons: either direction goes to the other one.
    const onCancel = document.activeElement === cancelButton.value
    ;(onCancel ? confirmButton : cancelButton).value?.focus()
  }
}
</script>

<template>
  <div
    data-test="bypass-overlay"
    class="fixed inset-0 z-40 flex items-center justify-center bg-bg/70 p-4"
    @click.self="emit('cancel')"
    @keydown="onKey"
  >
    <div
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="bypass-title"
      aria-describedby="bypass-text"
      class="flex max-w-md flex-col gap-3 rounded-lg border border-secondary/50 bg-elevated p-5"
    >
      <h3 id="bypass-title" class="m-0 text-base font-semibold text-secondary">Ativar "Sem perguntas"?</h3>
      <p id="bypass-text" class="m-0 text-sm text-fg">
        O Claude vai editar arquivos e rodar comandos nesta máquina sem pedir sua permissão.
        Um erro dele pode apagar dados ou alterar coisas fora do projeto. Use só quando confiar na tarefa.
      </p>
      <div class="flex justify-end gap-2">
        <button
          type="button"
          ref="cancelButton"
          data-test="bypass-cancel"
          class="h-9 cursor-pointer rounded-md border border-line-strong bg-transparent px-3 text-sm text-fg hover:bg-card"
          @click="emit('cancel')"
        >Cancelar</button>
        <button
          ref="confirmButton"
          type="button"
          data-test="bypass-confirm"
          class="h-9 cursor-pointer rounded-md border-none bg-secondary px-3 text-sm font-semibold text-secondary-fg"
          @click="emit('confirm')"
        >Ativar sem perguntas</button>
      </div>
    </div>
  </div>
</template>
