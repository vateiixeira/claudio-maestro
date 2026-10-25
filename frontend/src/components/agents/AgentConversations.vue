<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { errorMessage, listSpecialistConversations, openSpecialistConversation } from '../../api/http'
import { formatRunDate } from '../../agents'
import type { SpecialistConversation } from '../../types/api'
import { useSpecialistsStore } from '../../stores/specialists'
import { BTN, BTN_PRIMARY, ERROR } from './styles'

const props = defineProps<{ agentId: number }>()
const router = useRouter()
const store = useSpecialistsStore()
const conversations = ref<SpecialistConversation[]>([])
const loading = ref(true)
const opening = ref(false)
const error = ref<string | null>(null)
let ticket = 0
async function load() {
  const mine = ++ticket
  try {
    const fresh = await listSpecialistConversations(props.agentId)
    if (mine === ticket) { conversations.value = fresh; error.value = null }
  } catch (e) {
    if (mine === ticket) error.value = errorMessage(e)
  } finally {
    if (mine === ticket) loading.value = false
  }
}
async function open(input: { session_id?: string; new?: boolean } = {}) {
  if (opening.value) return
  opening.value = true
  error.value = null
  try {
    const chat = await openSpecialistConversation(props.agentId, input)
    await router.push({ name: 'session', params: { id: chat.session_id } })
  } catch (e) {
    error.value = errorMessage(e)
  } finally { opening.value = false }
}
onMounted(load)
watch(() => store.changes[props.agentId], load)
</script>

<template>
  <section aria-label="Conversas com o agente" class="flex flex-col gap-5">
    <div class="flex flex-col gap-3">
      <p class="m-0 max-w-prose text-sm leading-relaxed text-fg-muted">Converse com este agente usando a skill e os acessos configurados. Continue um assunto ou comece outra conversa para mudar de contexto.</p>
      <div class="flex flex-wrap gap-2">
        <button type="button" data-test="agent-chat-open" :class="BTN_PRIMARY" :disabled="opening" @click="open()">{{ opening ? 'Abrindo…' : 'Conversar com o agente' }}</button>
        <button type="button" data-test="agent-chat-new" :class="BTN" :disabled="opening" @click="open({ new: true })">Nova conversa</button>
      </div>
      <p class="m-0 text-xs text-fg-subtle">As mensagens seguem a fila do agente. As rotinas agendadas mantêm conversas próprias.</p>
    </div>
    <p v-if="error" role="alert" :class="ERROR">{{ error }}</p>
    <p v-if="loading" role="status" class="m-0 text-sm text-fg-subtle">Carregando conversas…</p>
    <p v-else-if="!conversations.length" data-test="agent-chats-empty" class="m-0 text-sm text-fg-muted">Nenhuma conversa ainda. Comece com uma pergunta ou um pedido.</p>
    <ul v-else class="m-0 flex list-none flex-col p-0">
      <li v-for="chat in conversations" :key="chat.session_id" class="border-t border-line">
        <button type="button" data-test="agent-chat-row" class="flex w-full items-center justify-between gap-4 rounded-md py-3 text-left hover:bg-card focus-visible:outline-2 focus-visible:outline-primary disabled:opacity-50" :disabled="opening" @click="open({ session_id: chat.session_id })">
          <span class="min-w-0 truncate text-sm font-medium">{{ chat.title }}</span>
          <span class="shrink-0 text-xs text-fg-subtle">{{ chat.finished ? 'Finalizada' : 'Aberta' }} · {{ formatRunDate(chat.last_activity_at) }}</span>
        </button>
      </li>
    </ul>
  </section>
</template>
