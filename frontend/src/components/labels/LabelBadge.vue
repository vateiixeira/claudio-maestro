<script setup lang="ts">
import { computed } from 'vue'
import { labelStyle } from '../../labelColor'
import type { Label } from '../../types/api'

// `wrap` drops the width cap: the whole name shows, breaking inside the badge only when it is wider than the line.
const props = defineProps<{ label: Label; compact?: boolean; wrap?: boolean }>()
const style = computed(() => labelStyle(props.label.color))
</script>

<template>
  <span
    data-test="label-badge"
    :data-slug="label.slug"
    :title="label.slug"
    :style="style"
    class="inline-flex shrink-0 items-center gap-1.5 px-2 font-mono leading-[1.125rem]"
    :class="[
      compact ? 'text-[0.625rem]' : 'text-[0.6875rem]',
      wrap ? 'max-w-full rounded-[0.5625rem] [overflow-wrap:anywhere]' : ['truncate rounded-full', compact ? 'max-w-20' : 'max-w-40'],
    ]"
  >
    <span
      data-test="label-dot"
      aria-hidden="true"
      class="size-2 shrink-0 rounded-full border border-fg-subtle"
      style="background: var(--label-dot)"
    />
    <span class="min-w-0" :class="wrap ? '[overflow-wrap:anywhere]' : 'truncate'">{{ label.slug }}</span>
  </span>
</template>
