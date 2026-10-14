<script setup lang="ts">
import type { PrimaryAction } from '../../../git/primaryAction'

defineProps<{ action: PrimaryAction; busy: string | null; available: boolean }>()
const emit = defineEmits<{ run: [] }>()
</script>

<template>
  <button
    type="button"
    data-test="primary-action"
    :disabled="!!busy || action.disabled || !available"
    :aria-busy="busy ? 'true' : 'false'"
    :title="busy ? undefined : (action.reason ?? undefined)"
    class="flex h-[26px] w-full items-center justify-center gap-1.5 rounded-md bg-elevated text-[0.8125rem] font-medium text-fg hover:bg-line-strong focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-default disabled:text-fg-subtle disabled:hover:bg-elevated"
    @click="emit('run')"
  >
    <svg v-if="busy" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true" class="motion-safe:animate-spin"><path d="M21 12a9 9 0 1 1-6.22-8.56" /></svg>
    <span>{{ busy ?? action.label }}</span>
  </button>
</template>
