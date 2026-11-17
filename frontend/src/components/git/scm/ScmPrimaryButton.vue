<script setup lang="ts">
import { computed } from 'vue'
import type { PrimaryAction } from '../../../git/primaryAction'

const props = defineProps<{ action: PrimaryAction; busy: string | null; available: boolean }>()
const emit = defineEmits<{ run: [] }>()
/** Green when it can act; while busy it stays green (the spinner says why it is waiting). */
const off = computed(() => !props.busy && (props.action.disabled || !props.available))
</script>

<template>
  <button
    type="button"
    data-test="primary-action"
    :disabled="!!busy || action.disabled || !available"
    :aria-busy="busy ? 'true' : 'false'"
    :title="busy ? undefined : (action.reason ?? undefined)"
    :class="off ? 'bg-elevated text-fg-muted' : 'bg-primary text-primary-fg hover:bg-primary-soft'"
    class="inline-flex h-8 min-w-0 shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-lg px-3.5 text-[0.8125rem] font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-default"
    @click="emit('run')"
  >
    <svg v-if="busy" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true" class="motion-safe:animate-spin"><path d="M21 12a9 9 0 1 1-6.22-8.56" /></svg>
    <span>{{ busy ?? action.label }}</span>
  </button>
</template>
