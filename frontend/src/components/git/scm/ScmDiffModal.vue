<script lang="ts">
let scrollLocks = 0
let savedOverflow = ''
</script>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, onUnmounted, ref, useId } from 'vue'
import FileDiffView from '../../details/FileDiffView.vue'
import type { ChangedFile, ChangesGroup } from '../../../types/api'

const props = defineProps<{
  projectId: number
  group: ChangesGroup
  file: ChangedFile
  revision: number
  conflictLabels?: { ours: string; theirs: string } | null
  returnFocus: HTMLElement | null
  fallbackFocus: HTMLElement | null
}>()
const emit = defineEmits<{ close: [] }>()
const titleId = useId()
const descriptionId = useId()
const panel = ref<HTMLElement | null>(null)
const closeButton = ref<HTMLButtonElement | null>(null)
const fileName = computed(() => props.file.rel_path.slice(props.file.rel_path.lastIndexOf('/') + 1))
const scope = computed(() => props.file.diff_scope === 'staged' ? 'Preparado' : props.file.diff_scope === 'combined' ? 'Conflito' : 'Alterações')

onMounted(async () => {
  if (scrollLocks++ === 0) {
    savedOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
  }
  document.addEventListener('keydown', onKeydown, true)
  await nextTick()
  closeButton.value?.focus()
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown, true)
  if (--scrollLocks === 0) document.body.style.overflow = savedOverflow
})
onUnmounted(async () => {
  await nextTick()
  const target = props.returnFocus?.isConnected ? props.returnFocus : props.fallbackFocus
  if (target?.isConnected) target.focus()
})
function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    emit('close')
    return
  }
  if (event.key !== 'Tab' || !panel.value) return
  const items = [...panel.value.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])')]
  const first = items[0]
  const last = items[items.length - 1]
  if (!first || !last) return
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
  <Teleport to="body">
    <div data-test="scm-diff-backdrop" class="fixed inset-0 z-50 flex items-center justify-center bg-bg/80 p-2 sm:p-4" @click.self="emit('close')">
      <section ref="panel" data-test="scm-diff-modal" role="dialog" aria-modal="true" :aria-labelledby="titleId" :aria-describedby="descriptionId" class="flex h-[96dvh] w-[96vw] max-w-[1600px] min-w-0 flex-col overflow-hidden rounded-lg border border-line-strong bg-panel shadow-2xl sm:h-[90dvh] sm:w-[90vw]">
        <header class="flex shrink-0 items-start gap-3 border-b border-line bg-elevated px-4 py-3">
          <div class="min-w-0 grow">
            <h2 :id="titleId" class="m-0 text-base font-semibold break-words text-fg">{{ fileName }}</h2>
            <p :id="descriptionId" class="m-0 mt-1 break-all font-mono text-xs text-fg-muted">{{ group.path }} / {{ file.rel_path }}</p>
            <span data-test="scm-diff-scope" class="mt-2 inline-flex rounded bg-card px-2 py-0.5 text-xs font-medium text-fg-muted">{{ scope }}</span>
          </div>
          <button ref="closeButton" type="button" data-test="scm-diff-close" aria-label="Fechar diff" title="Fechar diff (Esc)" class="flex size-9 shrink-0 items-center justify-center rounded-md text-fg-muted hover:bg-card hover:text-fg focus-visible:outline-2 focus-visible:outline-primary" @click="emit('close')">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" /></svg>
          </button>
        </header>
        <div tabindex="0" aria-label="Conteúdo do diff" class="min-h-0 min-w-0 flex-1 overflow-auto overscroll-contain p-3 outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-inset sm:p-4">
          <FileDiffView :project-id="projectId" :group="group" :file="file" :revision="revision" :conflict-labels="conflictLabels" />
        </div>
      </section>
    </div>
  </Teleport>
</template>
