<script setup lang="ts">
// Presentation-only layer behind the message textarea: it repeats the text in a
// transparent color so the chosen @mentions can be highlighted and the command's
// argument hint shown after the text. The parent passes the textarea's border,
// padding and font classes, so both lay the text out the same way. It scrolls
// (overflow-y-auto, invisible scrollbar) instead of clipping so that it reserves the
// same scrollbar width as the textarea and wraps the lines at the same places.
import { computed, onMounted, ref, watch } from 'vue'
import { mentionRanges } from '../../conversation/suggestions'

const props = defineProps<{ text: string; mentions: Set<string>; hint: string; scrollTop: number }>()

const el = ref<HTMLElement | null>(null)

const parts = computed(() => {
  const result: { text: string; mark: boolean }[] = []
  let at = 0
  for (const [start, end] of mentionRanges(props.text, props.mentions)) {
    if (start > at) result.push({ text: props.text.slice(at, start), mark: false })
    result.push({ text: props.text.slice(start, end), mark: true })
    at = end
  }
  if (at < props.text.length) result.push({ text: props.text.slice(at), mark: false })
  return result
})

function syncScroll() {
  if (el.value) el.value.scrollTop = props.scrollTop
}
watch(() => props.scrollTop, syncScroll, { flush: 'post' })
// The content grows after the text changes; the scroll position is applied once it has.
watch(() => [props.text, props.hint], syncScroll, { flush: 'post' })
onMounted(syncScroll)
</script>

<template>
  <div ref="el" aria-hidden="true" class="pointer-events-none absolute inset-0 overflow-x-hidden overflow-y-auto break-words whitespace-pre-wrap text-transparent [scrollbar-color:transparent_transparent]"><template v-for="(part, i) in parts" :key="i"><mark v-if="part.mark" class="rounded bg-primary/25 text-transparent">{{ part.text }}</mark><template v-else>{{ part.text }}</template></template><span v-if="hint" class="text-fg-muted">{{ hint }}</span>&#8203;</div>
</template>
