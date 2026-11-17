<script setup lang="ts">
defineProps<{ label: string; count?: number; pressed?: boolean }>()
defineEmits<{ toggle: [] }>()
</script>

<template>
  <button
    type="button"
    data-test="filter-chip"
    :aria-pressed="pressed ? 'true' : 'false'"
    class="inline-flex h-[30px] cursor-pointer items-center gap-[7px] rounded-full border px-[11px] text-[0.78125rem] whitespace-nowrap hover:bg-card hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
    :class="pressed ? 'border-fg-muted bg-card text-fg' : 'border-line text-fg-muted'"
    @click="$emit('toggle')"
  >
    <slot name="icon" />
    <span>{{ label }}</span>
    <span v-if="count !== undefined" data-test="filter-chip-count" class="font-mono text-[0.71875rem] text-fg-subtle tabular-nums">{{ count }}</span>
  </button>
</template>
