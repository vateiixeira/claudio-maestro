<script setup lang="ts">
import { useId } from 'vue'
defineProps<{ title: string; hint?: string }>()
const titleId = useId()
</script>

<template>
  <section :aria-labelledby="titleId" class="agent-section">
    <div class="agent-section-label">
      <h4 :id="titleId" data-test="section-title">{{ title }}</h4>
      <p v-if="hint">{{ hint }}</p>
    </div>
    <div class="agent-section-content"><slot /></div>
  </section>
</template>

<style scoped>
.agent-section { display:grid; min-width:0; gap:16px; border-top:1px solid var(--color-line); padding:24px 0; }
.agent-section-label { min-width:0; }
h4 { margin:0; color:var(--color-fg); font-size:13px; font-weight:500; line-height:1.5; }
.agent-section-label p { max-width:38ch; margin:6px 0 0; color:var(--color-fg-subtle); font-size:12px; line-height:1.6; }
.agent-section-content { display:flex; min-width:0; flex-direction:column; align-items:stretch; gap:12px; }
@container (min-width:780px) { .agent-section { grid-template-columns:190px minmax(0,1fr); gap:36px; padding:28px 0; } }
</style>
