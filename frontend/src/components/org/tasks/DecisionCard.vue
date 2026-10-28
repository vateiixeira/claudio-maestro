<script setup lang="ts">
import type { Decision } from '../../../types/org'

// Shell: a decision waiting for the person. T4 adds the options, the answer and the errors.
defineProps<{ decision: Decision }>()
</script>

<template>
  <article data-test="decision-card" :data-decision-id="decision.id" class="rounded-lg border border-line bg-panel p-3">
    <p class="m-0 text-sm text-fg">{{ decision.question }}</p>
  </article>
</template>
