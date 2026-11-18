<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { needsYouQueue, nextNeedsYou } from '../../nextNeedsYou'
import { useSessionsStore } from '../../stores/sessions'

const props = defineProps<{ currentId: string }>()

const sessions = useSessionsStore()
const router = useRouter()

// The same queue as the Inbox's "Aguardando você" tab, without the open conversation; the click walks it in order.
const queue = computed(() => needsYouQueue(sessions.all, props.currentId))

function goNext() {
  const next = nextNeedsYou(sessions.all, props.currentId)
  if (next) void router.push({ name: 'session', params: { id: next.session_id } })
}
</script>

<template>
  <button
    v-if="queue.length > 0"
    type="button"
    data-test="next-needs-you"
    :title="`Abrir a próxima conversa que aguarda você, sem contar esta (n). Outras aguardando: ${queue.length}`"
    :aria-label="`Próxima conversa que aguarda você, ${queue.length} ${queue.length === 1 ? 'outra' : 'outras'}`"
    aria-keyshortcuts="n"
    class="inline-flex h-[30px] shrink-0 items-center gap-[7px] rounded-lg bg-secondary-tint py-0 pr-2 pl-2.5 text-[0.78125rem] font-medium whitespace-nowrap text-secondary-soft hover:brightness-110 focus-visible:outline-2 focus-visible:outline-primary"
    @click="goNext"
  >
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
    <span>Próxima</span>
    <span data-test="next-count" class="inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-secondary px-[5px] font-mono text-[0.65625rem] font-semibold text-secondary-fg">{{ queue.length }}</span>
  </button>
</template>
