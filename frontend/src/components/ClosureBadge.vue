<script setup lang="ts">
import { computed } from 'vue'
import { CLOSURE_BADGE_CLASS, CLOSURE_DOT_CLASS, CLOSURE_LABELS, shownVerdict } from '../closure'
import type { Session } from '../types/api'

const props = defineProps<{ session: Pick<Session, 'display_state' | 'closure_verdict'>; compact?: boolean }>()
const verdict = computed(() => shownVerdict(props.session))
</script>

<template>
  <span
    v-if="verdict && compact"
    data-test="closure-dot"
    role="img"
    :title="CLOSURE_LABELS[verdict]"
    :aria-label="CLOSURE_LABELS[verdict]"
    class="size-2 shrink-0 rounded-full"
    :class="CLOSURE_DOT_CLASS[verdict]"
  />
  <span
    v-else-if="verdict"
    data-test="closure-badge"
    class="shrink-0 rounded-full border px-1.5 font-mono text-[0.6875rem]"
    :class="CLOSURE_BADGE_CLASS[verdict]"
  >{{ CLOSURE_LABELS[verdict] }}</span>
</template>
