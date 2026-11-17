<script setup lang="ts">
defineOptions({ inheritAttrs: false })

const props = defineProps<{ modelValue: boolean; label: string; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

// Space toggles on keyup, but only when the press started on this button.
let spaceDown = false
function onSpaceUp() {
  if (!spaceDown) return
  spaceDown = false
  toggle()
}

function toggle() {
  if (props.disabled) return
  emit('update:modelValue', !props.modelValue)
}
</script>

<template>
  <!-- Space is handled on keyup with preventDefault so the browser's own click
       (also fired on keyup) does not toggle a second time. -->
  <button
    type="button"
    role="switch"
    data-test="toggle-switch"
    v-bind="$attrs"
    :aria-checked="modelValue ? 'true' : 'false'"
    :aria-label="label"
    :disabled="disabled"
    class="relative h-5 w-[34px] flex-none cursor-pointer rounded-full border p-0 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-default disabled:opacity-50"
    :class="modelValue ? 'border-primary bg-primary' : 'border-fg-subtle bg-line-strong'"
    @click="toggle"
    @keydown.space.prevent="spaceDown = true"
    @keyup.space.prevent="onSpaceUp"
    @blur="spaceDown = false"
  >
    <span
      aria-hidden="true"
      class="absolute top-[2px] left-[2px] size-3.5 rounded-full transition-transform"
      :class="modelValue ? 'translate-x-[14px] bg-primary-fg' : 'bg-fg-muted'"
    />
  </button>
</template>
