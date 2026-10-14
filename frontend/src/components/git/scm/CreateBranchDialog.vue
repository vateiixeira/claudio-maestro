<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import ConfirmDialog from '../../ConfirmDialog.vue'
import { branchNameProblem } from '../../../git/branchName'

const props = defineProps<{ from: string; sha: string | null; changes: number; initial: string; error: string | null; busy: boolean }>()
const emit = defineEmits<{ submit: [name: string]; cancel: [] }>()

const name = ref(props.initial)
const input = ref<HTMLInputElement | null>(null)
const problem = computed(() => branchNameProblem(name.value))
// The server's refusal is about the name that was sent: typing another one takes it away.
const serverError = ref(props.error)
watch(() => props.error, (now) => { serverError.value = now })
watch(name, () => { serverError.value = null })
const shown = computed(() => problem.value ?? serverError.value)
const disabled = computed(() => props.busy || !name.value.trim() || problem.value != null)
const carried = computed(() => {
  if (props.changes === 0) return ''
  return props.changes === 1 ? ' A alteração não commitada vai junto.' : ` As ${props.changes} alterações não commitadas vão junto.`
})

onMounted(async () => {
  await nextTick()
  input.value?.focus()
})

function submit(): void {
  if (!disabled.value) emit('submit', name.value.trim())
}
</script>

<template>
  <ConfirmDialog title="Criar branch" confirm-label="Criar branch" :confirm-disabled="disabled" :autofocus="false" @confirm="submit" @cancel="emit('cancel')">
    <input
      ref="input"
      v-model="name"
      type="text"
      data-test="branch-name"
      aria-label="Nome da branch"
      placeholder="feat/nome-da-branch"
      class="h-9 w-full rounded-lg border border-line-strong bg-surface px-3 font-mono text-sm text-fg placeholder:text-fg-subtle focus:border-fg-muted focus:outline-none"
      @keydown.enter.prevent="submit"
    >
    <p class="m-0 text-sm leading-relaxed text-fg-muted">Sai de {{ from }}<template v-if="sha"> ({{ sha }})</template> e troca para ela.{{ carried }}</p>
    <p v-if="shown" data-test="branch-error" role="alert" class="m-0 text-xs text-diff-del-fg">{{ shown }}</p>
  </ConfirmDialog>
</template>
