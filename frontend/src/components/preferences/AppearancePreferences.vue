<script setup lang="ts">
import GroupHeader from '../ui/GroupHeader.vue'
import ThemePicker from './ThemePicker.vue'
import { UI_SCALES, setUiScale, uiScale } from '../../uiScale'

const scaleLabel = (scale: number) => `${Math.floor(scale)}%`
</script>

<template>
  <div class="flex flex-col gap-7 px-7 py-6" aria-label="Preferências de aparência" role="group">
    <p class="m-0 text-xs text-fg-muted">Tudo aqui vale só neste navegador e muda na hora — não precisa salvar.</p>

    <section aria-label="Tema" class="flex flex-col gap-3">
      <ThemePicker />
    </section>

    <section aria-describedby="pref-ui-scale-help" class="flex flex-col gap-2">
      <GroupHeader title="Tamanho do texto" />
      <div class="flex flex-wrap gap-1.5">
        <label
          v-for="scale in UI_SCALES"
          :key="scale"
          data-test="ui-scale-option"
          class="flex h-11 min-w-16 cursor-pointer items-center justify-center rounded-lg border px-3.5 text-sm font-medium has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-fg-muted"
          :class="uiScale === scale ? 'border-line-strong bg-card text-fg' : 'border-line text-fg-muted hover:bg-card hover:text-fg'"
        >
          <input
            type="radio"
            name="ui-scale"
            :value="scale"
            :checked="uiScale === scale"
            class="sr-only"
            @change="setUiScale(scale)"
          />
          {{ scaleLabel(scale) }}
        </label>
      </div>
      <p id="pref-ui-scale-help" class="m-0 text-xs text-fg-muted">
        Útil em telas 4K. A escolha fica guardada neste navegador.
      </p>
    </section>
  </div>
</template>
