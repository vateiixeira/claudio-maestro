<script setup lang="ts">
import type { DisplayState, Session } from '../../types/api'
import DisplayStateIcon from '../DisplayStateIcon.vue'
import SessionRow from './SessionRow.vue'

// A titled group of sessions sharing one displayed state.
defineProps<{ display: DisplayState; title: string; sessions: Session[]; showProject?: boolean }>()
const emit = defineEmits<{ error: [message: string] }>()
</script>

<template>
  <section :id="display === 'finished' ? 'finalizadas' : undefined" :aria-label="title" class="flex flex-col gap-2">
    <div class="flex items-center gap-2">
      <DisplayStateIcon :display="display" :size="10" />
      <h2
        class="m-0 text-sm font-semibold"
        :class="display === 'running' ? 'text-primary-soft' : display === 'waiting' ? 'text-secondary' : 'text-fg-muted'"
      >
        {{ title }}
      </h2>
      <span class="font-mono text-xs text-fg-muted">{{ sessions.length }}</span>
    </div>
    <slot name="empty" v-if="sessions.length === 0" />
    <SessionRow
      v-for="session in sessions"
      :key="session.session_id"
      :session="session"
      :show-project="showProject"
      @error="emit('error', $event)"
    />
  </section>
</template>
