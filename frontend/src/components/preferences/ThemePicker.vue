<script setup lang="ts">
import { THEMES, setTheme, theme } from '../../theme'
</script>

<template>
  <fieldset class="m-0 flex min-w-0 flex-col gap-2 border-0 p-0" aria-describedby="pref-theme-help">
    <legend class="mb-2 p-0 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Tema</legend>
    <div class="grid grid-cols-[repeat(auto-fill,minmax(11rem,1fr))] gap-2">
      <label
        v-for="item in THEMES"
        :key="item.id"
        data-test="theme-option"
        :data-theme-id="item.id"
        class="flex min-h-11 cursor-pointer items-center gap-3 rounded-lg border px-3.5 py-2 text-sm font-medium has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-fg-muted"
        :class="theme === item.id ? 'border-line-strong bg-card text-fg' : 'border-line text-fg-muted hover:bg-card hover:text-fg'"
      >
        <input
          type="radio"
          name="theme"
          :value="item.id"
          :checked="theme === item.id"
          class="sr-only"
          @change="setTheme(item.id)"
        />
        <span class="flex shrink-0 -space-x-1" aria-hidden="true">
          <span
            v-for="(color, index) in item.swatch"
            :key="index"
            data-test="theme-swatch"
            class="size-4 rounded-full border border-line-strong"
            :style="{ backgroundColor: color }"
          />
        </span>
        {{ item.label }}
      </label>
    </div>
    <p id="pref-theme-help" class="m-0 text-xs text-fg-muted">Vale só neste navegador e muda na hora.</p>
  </fieldset>
</template>
