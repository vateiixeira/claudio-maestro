<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { useSpecialistsStore } from '../../stores/specialists'
import { errorMessage, listSpecialistMessages } from '../../api/http'
import { BTN_SMALL, ERROR } from './styles'

const props = defineProps<{ agentId: number; sessionId: string }>()
const store = useSpecialistsStore()
const agent = computed(() => store.byId(props.agentId))
const pending = computed(() => store.runsOf(props.agentId).filter((run) => run.message && run.session_id === props.sessionId && (run.outcome === 'queued' || run.outcome === 'starting')).sort((a, b) => a.id - b.id))
const previews = ref<Record<number, string>>({})
let previewTicket = 0
async function loadPreviews() {
  const mine = ++previewTicket
  try {
    const messages = await listSpecialistMessages(props.agentId, props.sessionId)
    if (mine === previewTicket) previews.value = Object.fromEntries(messages.map((message) => [message.id, message.text]))
  } catch (e) { if (mine === previewTicket) error.value = errorMessage(e) }
}
const error = ref<string | null>(null)
const cancelling = ref(new Set<number>())
async function load() {
  try { await store.loadRuns(props.agentId); error.value = null }
  catch (e) { error.value = errorMessage(e) }
}
async function cancel(id: number) {
  if (cancelling.value.has(id)) return
  cancelling.value.add(id)
  try { await store.cancelRun(props.agentId, id); error.value = null }
  catch (e) { error.value = errorMessage(e) }
  finally { cancelling.value.delete(id) }
}
onMounted(load)
watch(() => store.changes[props.agentId], load)
watch(() => pending.value.map((run) => run.id).join(','), () => { void loadPreviews() }, { immediate: true })
</script>

<template>
  <aside aria-label="Fila da conversa" data-test="agent-chat-queue" class="shrink-0 border-b border-line px-4 py-2 text-xs">
    <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
      <RouterLink :to="{ name: 'agents', params: { id: agentId } }" class="text-info-soft hover:text-fg">{{ agent?.name ?? 'Agente' }}</RouterLink>
      <span class="text-fg-muted">{{ agent?.queue_paused ? 'Fila pausada' : pending.length ? 'Mensagem na fila' : 'Conversa com o agente' }}</span>
      <RouterLink :to="{ name: 'agents', params: { id: agentId }, query: { aba: 'runs' } }" class="text-fg-muted hover:text-fg">Ver fila e execuções</RouterLink>
    </div>
    <ul v-if="pending.length" class="m-0 mt-2 flex max-h-32 list-none flex-col gap-1 overflow-y-auto p-0">
      <li v-for="(run, index) in pending" :key="run.id" data-test="chat-queued-message" class="flex items-center gap-3">
        <div class="min-w-0 grow">
          <span class="text-fg-subtle">Mensagem {{ index + 1 }} · {{ run.outcome === 'starting' ? 'Iniciando' : 'Aguardando envio' }}</span>
          <p class="m-0 truncate text-sm text-fg-muted">{{ previews[run.id] || 'Mensagem com imagem' }}</p>
        </div>
        <button v-if="run.outcome === 'queued'" type="button" data-test="chat-queue-cancel" :class="BTN_SMALL" :disabled="cancelling.has(run.id)" @click="cancel(run.id)">Cancelar</button>
      </li>
    </ul>
    <p v-if="error" role="alert" :class="[ERROR, 'mt-1']">{{ error }}</p>
  </aside>
</template>
