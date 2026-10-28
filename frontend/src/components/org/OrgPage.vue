<script setup lang="ts">
import { inject } from 'vue'
import { AGENTS_NAVIGATION_KEY } from '../../agentsNavigation'
defineProps<{ title: string; eyebrow?: string }>()
const navigation = inject(AGENTS_NAVIGATION_KEY, undefined)
</script>
<template>
  <div class="org-page">
    <header class="org-heading">
      <button v-if="navigation?.enabled.value" class="org-menu" type="button" aria-label="Abrir navegação" :aria-expanded="navigation.open.value" @click="navigation.toggle($event.currentTarget as HTMLElement)"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" /></svg></button>
      <div class="grow min-w-0"><p v-if="eyebrow" class="org-eyebrow">{{ eyebrow }}</p><h1>{{ title }}</h1></div><slot name="actions" />
    </header>
    <div class="org-body"><slot /></div>
  </div>
</template>
<style src="./org.css"></style>
