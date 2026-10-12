<script setup lang="ts">
import { computed, ref } from 'vue'
import { THEMES, setTheme, theme, type ThemeId } from '../../theme'
import ThemePreview from './ThemePreview.vue'

// The preview follows the card under the mouse, then the one with keyboard focus, then the active theme.
const hovered = ref<ThemeId | null>(null)
const focused = ref<ThemeId | null>(null)
const previewId = computed<ThemeId>(() => hovered.value ?? focused.value ?? theme.value)
const previewLabel = computed(() => THEMES.find((t) => t.id === previewId.value)?.label ?? '')
</script>

<template>
  <fieldset class="m-0 flex min-w-0 flex-col gap-2 border-0 p-0" aria-describedby="pref-theme-help">
    <legend class="mb-2 p-0 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Tema</legend>
    <div class="grid grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] gap-2">
      <!-- Each card is painted with its own theme (data-theme scopes the variables to the card). -->
      <label
        v-for="item in THEMES"
        :key="item.id"
        data-test="theme-option"
        :data-theme="item.id"
        class="flex min-w-0 cursor-pointer flex-col gap-1.5 rounded-lg border bg-panel px-3.5 py-2.5 text-fg has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-fg-muted"
        :class="theme === item.id ? 'border-fg' : 'border-line hover:border-line-strong'"
        @mouseenter="hovered = item.id"
        @mouseleave="hovered = null"
        @focusin="focused = item.id"
        @focusout="focused = null"
      >
        <input
          type="radio"
          name="theme"
          :value="item.id"
          :checked="theme === item.id"
          class="sr-only"
          @change="setTheme(item.id)"
        />
        <span class="flex items-center gap-2">
          <span data-test="theme-name" class="min-w-0 grow truncate text-sm font-medium">{{ item.label }}</span>
          <span
            v-if="theme === item.id"
            data-test="theme-active"
            class="shrink-0 rounded-full bg-primary px-2 py-px text-[0.6875rem] font-semibold text-primary-fg"
          >Ativo</span>
        </span>
        <span class="font-mono text-xs text-fg-muted" aria-hidden="true">
          <span :style="{ color: 'var(--color-syntax-keyword)' }">const</span>
          theme =
          <span :style="{ color: 'var(--color-syntax-string)' }">'ok'</span>
          <span :style="{ color: 'var(--color-syntax-comment)' }"> // {{ item.id }}</span>
        </span>
      </label>
    </div>
    <div class="mt-1 flex flex-col gap-2">
      <p data-test="theme-preview-caption" class="m-0 text-xs text-fg-muted">Prévia: {{ previewLabel }}</p>
      <ThemePreview :theme-id="previewId" />
    </div>
    <p id="pref-theme-help" class="m-0 text-xs text-fg-muted">
      Passe o mouse ou use as setas para ver cada tema na prévia. A escolha vale só neste navegador e muda na hora.
    </p>
  </fieldset>
</template>
