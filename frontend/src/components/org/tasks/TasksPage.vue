<script setup lang="ts">
import { inject } from 'vue'
import { AGENTS_NAVIGATION_KEY } from '../../../agentsNavigation'

// The frame of the task screens: the menu button on narrow windows, the title and the content in a readable width.
defineProps<{ title: string }>()
const navigation = inject(AGENTS_NAVIGATION_KEY, undefined)
</script>

<template>
  <div class="h-full min-w-0 overflow-y-auto bg-surface">
    <div class="mx-auto flex w-full max-w-[1100px] flex-col gap-5 px-4 py-6 lg:px-8">
      <header class="flex min-w-0 items-center gap-3">
        <button
          v-if="navigation?.enabled.value"
          type="button"
          data-test="tasks-mobile-menu"
          class="flex h-9 w-8 shrink-0 cursor-pointer items-center justify-center rounded-md border-0 bg-transparent text-fg-muted hover:bg-card hover:text-fg focus-visible:outline-2 focus-visible:outline-primary"
          aria-label="Abrir navegação"
          :aria-expanded="navigation.open.value"
          @click="navigation.toggle($event.currentTarget as HTMLElement)"
        >
          <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" /></svg>
        </button>
        <slot name="heading"><h1 class="m-0 min-w-0 grow text-2xl font-semibold tracking-tight">{{ title }}</h1></slot>
        <slot name="actions" />
      </header>
      <slot />
    </div>
  </div>
</template>
