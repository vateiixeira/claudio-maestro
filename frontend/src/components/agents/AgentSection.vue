<script setup lang="ts">
import { useId } from 'vue'

defineProps<{ title: string; hint?: string }>()
const titleId = useId()
</script>

<template>
  <section :aria-labelledby="titleId" class="flex flex-col gap-2.5 border-t border-line pt-5">
    <div class="flex flex-col gap-0.5">
      <h3 :id="titleId" data-test="section-title" class="m-0 font-mono text-[0.6875rem] font-normal tracking-[0.08em] text-fg-subtle uppercase">{{ title }}</h3>
      <p v-if="hint" class="m-0 text-xs text-fg-subtle">{{ hint }}</p>
    </div>
    <slot />
  </section>
</template>
