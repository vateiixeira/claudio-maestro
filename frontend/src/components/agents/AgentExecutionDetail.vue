<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { errorMessage, getSession } from '../../api/http'
import { useEventSocket } from '../../api/socket'
import { onCodeCopyClick } from '../../conversation/codeCopy'
import { renderMarkdown } from '../../conversation/markdown'
import { applyConversationEvent, conversationFromSnapshot, type Conversation } from '../../stores/conversation'
import type { WsEvent } from '../../types/events'

const props = defineProps<{ sessionId: string }>()
const emit = defineEmits<{ reveal: [] }>()
const socket = useEventSocket()
// A read-only view: its snapshot and subscriptions never replace the parent conversation's store.
const conversation = ref<Conversation | null>(null)
const error = ref<string | null>(null)
const loading = ref(true)
let reloadCurrent = () => {}
watch(() => props.sessionId, (id, _before, cleanup) => {
  let alive = true, fetching = false, again = false
  let buffer: WsEvent[] = []
  conversation.value = null
  error.value = null
  loading.value = true
  async function reload() {
    if (fetching) { again = true; return }
    fetching = true
    buffer = []
    try {
      const snapshot = await getSession(id)
      if (!alive) return
      const next = conversationFromSnapshot(snapshot)
      for (const event of buffer) {
        if (event.type === 'conversation.reset' && event.seq > next.seq) { again = true; break }
        if (event.seq > next.seq + 1) { again = true; break }
        applyConversationEvent(next, event)
      }
      conversation.value = next
      error.value = null
    } catch (e) { if (alive) error.value = errorMessage(e) }
    finally {
      fetching = false
      if (alive) {
        loading.value = false
        if (again) { again = false; void reload() }
      }
    }
  }
  const offSession = socket.onSession(id, incoming => {
    // Each panel owns the item payloads that its reducer mutates.
    const event = structuredClone(incoming)
    if (fetching) { buffer.push(event); return }
    if (event.type === 'conversation.reset' || !conversation.value || event.seq > conversation.value.seq + 1) { void reload(); return }
    applyConversationEvent(conversation.value, event)
  })
  const offOpen = socket.onOpen(() => { void reload() })
  reloadCurrent = () => { void reload() }
  void reload()
  cleanup(() => { alive = false; offSession(); offOpen() })
}, { immediate: true })
const currentItems = computed(() => {
  const items = conversation.value?.items ?? []
  let userIndex = items.length - 1
  while (userIndex >= 0 && items[userIndex]?.type !== 'user') userIndex--
  return items.slice(userIndex + 1)
})
const conclusion = computed(() => {
  const calls = currentItems.value.filter(item => item.type === 'tool' && item.name.endsWith('__concluir'))
  const last = calls.at(-1)
  return last?.type === 'tool' && typeof last.input.resumo === 'string' ? last.input.resumo : null
})
const messages = computed(() => currentItems.value.filter(item => item.type === 'text' && !item.parent_tool_use_id))
const activity = computed(() => {
  const item = currentItems.value.filter(item => item.type === 'tool').at(-1)
  return item?.type === 'tool' ? (typeof item.input.description === 'string' ? item.input.description : item.name.replace(/^mcp__[^_]+__/, '')) : null
})
const running = computed(() => conversation.value?.state === 'running' || conversation.value?.state === 'connecting')
watch(() => messages.value.map(item => 'text' in item ? item.text : '').join('').length, () => emit('reveal'), { flush: 'post' })
</script>

<template>
  <div data-test="agent-execution-detail" class="execution-detail">
    <p v-if="loading" role="status" class="execution-note">Carregando a execução…</p>
    <p v-if="error" role="alert" class="execution-note text-diff-del-fg">{{ error }} <button type="button" class="underline" @click="reloadCurrent">Tentar novamente</button></p>
    <template v-if="conversation">
      <p v-if="running && activity" data-test="execution-activity" class="execution-note">Em andamento: {{ activity }}</p>
      <p v-if="conversation.prompts.length" role="status" class="execution-note text-secondary-soft">Esta execução precisa de você. Abra os detalhes para responder ao pedido.</p>
      <p v-if="conversation.historyTruncated" class="execution-note">Mostrando as mensagens mais recentes desta execução.</p>
      <div class="execution-output" @click="onCodeCopyClick">
        <div v-if="conclusion" class="markdown execution-result" v-html="renderMarkdown(conclusion)" />
        <template v-else><div v-for="item in messages" :key="item.id" class="markdown execution-result" v-html="renderMarkdown('text' in item ? item.text : '')" /></template>
        <p v-if="!conclusion && !messages.length && !loading" class="execution-note">A execução ainda não escreveu uma resposta.</p>
      </div>
      <p v-if="conversation.error" role="alert" class="execution-note text-diff-del-fg">{{ conversation.error }}</p>
    </template>
    <RouterLink data-test="agent-execution-full" :to="{ name: 'session', params: { id: sessionId } }" class="execution-full">{{ conversation?.prompts.length ? 'Responder na execução' : 'Abrir execução completa' }}</RouterLink>
  </div>
</template>

<style scoped>
.execution-detail { min-width:0; border-top:1px solid var(--color-line); padding:16px; }
.execution-note { margin:0 0 12px; color:var(--color-fg-subtle); font-size:12px; line-height:1.7; overflow-wrap:anywhere; }
.execution-output { display:flex; max-height:480px; min-width:0; flex-direction:column; gap:16px; overflow:auto; overscroll-behavior:contain; scrollbar-gutter:stable; }
.execution-result { min-width:0; font-size:13px; line-height:1.75; overflow-wrap:anywhere; }
.execution-full { display:inline-flex; margin-top:14px; border-radius:4px; color:var(--color-info-soft); font-size:12px; text-decoration:none; }
.execution-full:hover { text-decoration:underline; }
.execution-full:focus-visible { outline:2px solid var(--color-primary); outline-offset:4px; }
@media (max-width:600px) { .execution-detail { padding:12px; } }
</style>
