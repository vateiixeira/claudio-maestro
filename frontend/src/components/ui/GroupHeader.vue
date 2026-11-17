<script setup lang="ts">
defineProps<{ title: string; count?: number }>()
</script>

<template>
  <div data-test="group-header" class="flex h-[34px] items-center gap-2 border-b border-line-strong">
    <span class="font-mono text-[0.65625rem] font-semibold tracking-[0.08em] text-fg-subtle uppercase">{{ title }}</span>
    <span v-if="count !== undefined" data-test="group-header-count" class="font-mono text-[0.71875rem] text-fg-subtle tabular-nums">{{ count }}</span>
    <span class="flex-1" />
    <slot />
  </div>
</template>
