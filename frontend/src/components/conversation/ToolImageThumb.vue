<script setup lang="ts">
import { computed, inject, onBeforeUnmount, onMounted, ref } from 'vue'
import { SESSION_ID_KEY } from '../../stores/changesPanel'
import { useToolImage, type ToolImageEntry } from '../../conversation/toolImages'

// One thumbnail of the strip: loads its image when it comes on screen (a long block can hold dozens of screenshots).
const props = defineProps<{ entry: ToolImageEntry; position: number; total: number; sessionActive?: boolean }>()
const emit = defineEmits<{ open: [] }>()

const sessionId = inject(SESSION_ID_KEY, null)
const root = ref<HTMLElement | null>(null)
const visible = ref(typeof IntersectionObserver === 'undefined')
let observer: IntersectionObserver | null = null
onMounted(() => {
  if (visible.value || !root.value) return
  observer = new IntersectionObserver((hits) => {
    if (hits.some((hit) => hit.isIntersecting)) {
      visible.value = true
      observer?.disconnect()
    }
  }, { rootMargin: '200px' })
  observer.observe(root.value)
})
onBeforeUnmount(() => observer?.disconnect())

const { url, state } = useToolImage(() => sessionId?.value ?? null, () => props.entry, () => props.sessionActive === true, visible)
const label = computed(() =>
  state.value === 'error' ? `Imagem ${props.position} de ${props.total} indisponível` : `Abrir imagem ${props.position} de ${props.total}`)
</script>

<template>
  <button
    ref="root"
    type="button"
    data-test="tool-image"
    class="relative flex h-22 min-w-22 shrink-0 cursor-pointer items-center justify-center overflow-hidden rounded-md border border-line bg-card p-0 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-default"
    :aria-label="label"
    :aria-busy="state === 'loading' || state === 'idle'"
    :disabled="state === 'error'"
    @click="emit('open')"
  >
    <img v-if="url" :src="url" alt="" draggable="false" class="block h-full w-auto max-w-56 object-cover" />
    <span v-else-if="state === 'error'" class="px-2 text-center text-xs text-fg-subtle">Imagem indisponível</span>
    <span v-else class="size-full animate-pulse bg-elevated" aria-hidden="true" />
  </button>
</template>
