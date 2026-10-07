<script setup lang="ts">
import IconCheck from '../icons/IconCheck.vue'
import IconClose from '../icons/IconClose.vue'
import { useUpdatesStore } from '../../stores/updates'

const updates = useUpdatesStore()
</script>

<template>
  <div
    v-if="updates.showUpdatedNotice && updates.state?.last_result"
    data-test="updated-notice"
    role="status"
    class="flex min-w-0 shrink-0 items-center gap-1.5 px-4 pb-1 font-mono text-xs text-fg-subtle"
  >
    <IconCheck :size="12" class="shrink-0 text-primary" />
    <span class="min-w-0 truncate">
      Atualizado para {{ updates.state.last_result.to }}
      <span class="text-fg-subtle">(antes {{ updates.state.last_result.from }})</span>
    </span>
    <button
      type="button"
      data-test="updated-dismiss"
      aria-label="Dispensar"
      class="ml-auto shrink-0 cursor-pointer rounded-sm border-none bg-transparent p-0.5 font-mono text-xs text-fg-subtle hover:text-fg"
      @click="updates.dismissUpdatedNotice()"
    ><IconClose :size="12" /></button>
  </div>
</template>
