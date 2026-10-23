<script setup lang="ts">
withDefaults(defineProps<{ size?: number }>(), { size: 15 })
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="shrink-0" aria-hidden="true">
    <rect x="4" y="8" width="16" height="12" rx="3" /><path d="M12 8V4" /><circle cx="12" cy="3.5" r="1" /><path d="M9 13.5v1" /><path d="M15 13.5v1" />
  </svg>
</template>
