<script setup lang="ts">
withDefaults(defineProps<{ size?: number }>(), { size: 14 })
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0" aria-hidden="true">
    <circle cx="12" cy="12" r="9" /><path d="M12 7.5v5" /><path d="M12 16.5h.01" />
  </svg>
</template>
