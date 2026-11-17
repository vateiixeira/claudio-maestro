<script setup lang="ts">
import { computed, ref } from 'vue'
import { LABEL_PALETTE } from '../../labelColor'

const props = defineProps<{ modelValue: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const NAMES = ['Rosa', 'Laranja', 'Amarelo', 'Verde', 'Ciano', 'Violeta', 'Cinza']

const colors = computed(() => LABEL_PALETTE.map((color, index) => ({ color, name: NAMES[index] ?? color })))
const current = computed(() => props.modelValue.trim().toLowerCase())
const isCustom = computed(() => /^#[0-9a-f]{3,6}$/.test(current.value) && !LABEL_PALETTE.includes(current.value))
// The native picker only takes #rrggbb.
const pickerValue = computed(() => (/^#[0-9a-f]{6}$/.test(current.value) ? current.value : LABEL_PALETTE[0]))

const picker = ref<HTMLInputElement | null>(null)
function onPick(event: Event) {
  emit('update:modelValue', (event.target as HTMLInputElement).value.toLowerCase())
}
</script>

<template>
  <div role="group" aria-label="Cor" class="relative flex flex-wrap items-center gap-2.5">
    <button
      v-for="item in colors"
      :key="item.color"
      type="button"
      data-test="palette-color"
      :data-color="item.color"
      :aria-label="item.name"
      :title="item.name"
      :aria-pressed="current === item.color ? 'true' : 'false'"
      :style="{ backgroundColor: item.color }"
      class="size-5 flex-none cursor-pointer rounded-full border-0 p-0 hover:scale-110 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary aria-pressed:shadow-[0_0_0_2px_var(--color-panel),0_0_0_4px_var(--color-fg)]"
      @click="emit('update:modelValue', item.color)"
    />
    <button
      type="button"
      data-test="palette-custom"
      :aria-pressed="isCustom ? 'true' : 'false'"
      class="cursor-pointer rounded-sm border-0 bg-transparent p-0 text-xs text-fg-muted underline underline-offset-[3px] hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary aria-pressed:text-fg"
      @click="picker?.click()"
    >
      <span
        v-if="isCustom"
        data-test="palette-custom-swatch"
        aria-hidden="true"
        :style="{ backgroundColor: current }"
        class="mr-1.5 inline-block size-3 rounded-full align-[-2px] shadow-[0_0_0_1px_var(--color-fg-subtle)]"
      />Outra…</button>
    <input
      ref="picker"
      type="color"
      tabindex="-1"
      aria-hidden="true"
      :value="pickerValue"
      class="pointer-events-none absolute size-0 opacity-0"
      @input="onPick"
    />
  </div>
</template>
