<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { needsYouQueue } from '../../nextNeedsYou'
import { useSessionsStore } from '../../stores/sessions'

const props = defineProps<{ currentId: string }>()

const sessions = useSessionsStore()
const router = useRouter()

// The same queue as the Inbox's "Aguardando você" tab, without the open conversation.
const queue = computed(() => needsYouQueue(sessions.all, props.currentId))

function goNext() {
  const next = queue.value[0]
  if (next) void router.push({ name: 'session', params: { id: next.session_id } })
}
</script>

<template>
  <button
    v-if="queue.length > 0"
    type="button"
    data-test="next-needs-you"
    title="Abrir a próxima conversa que aguarda você (N)"
    class="flex h-8 shrink-0 items-center gap-1.5 rounded-md border border-line-strong px-2.5 text-sm font-medium text-fg hover:bg-card focus-visible:outline-2 focus-visible:outline-primary"
    @click="goNext"
  >
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-secondary" aria-hidden="true">
      <line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" />
    </svg>
    <span>Próxima ({{ queue.length }})</span>
  </button>
</template>
