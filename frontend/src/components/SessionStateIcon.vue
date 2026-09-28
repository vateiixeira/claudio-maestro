<script setup lang="ts">
import { computed } from 'vue'
import type { SessionState } from '../types/api'
import { stateShape } from '../sessionState'

const props = withDefaults(defineProps<{ state: SessionState; size?: number }>(), { size: 12 })

const shape = computed(() => stateShape(props.state))
</script>

<template>
  <!-- Fixed-width slot so titles line up whether or not there is an icon. -->
  <span
    class="flex shrink-0 items-center justify-center"
    :style="{ width: `${size}px` }"
    :data-shape="shape"
    aria-hidden="true"
  >
    <span
      v-if="shape === 'circle'"
      class="rounded-full bg-primary"
      :class="{ 'animate-pulse': state === 'connecting' }"
      :style="{ width: `${size * 0.67}px`, height: `${size * 0.67}px` }"
    />
    <svg
      v-else-if="shape === 'triangle'"
      :width="size"
      :height="size"
      viewBox="0 0 24 24"
      fill="none"
      class="stroke-secondary"
      stroke-width="2.4"
      stroke-linecap="round"
      stroke-linejoin="round"
    >
      <path d="M12 3 2 20h20L12 3z" />
      <line x1="12" y1="10" x2="12" y2="14" />
      <line x1="12" y1="17" x2="12" y2="17.01" />
    </svg>
  </span>
</template>
