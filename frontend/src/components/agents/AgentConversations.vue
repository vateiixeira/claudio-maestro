<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { errorMessage, listSpecialistConversations, openSpecialistConversation } from '../../api/http'
import { formatRunDate } from '../../agents'
import type { SpecialistConversation } from '../../types/api'
import { useSpecialistsStore } from '../../stores/specialists'
import IconPlus from '../icons/IconPlus.vue'
import IconArrowUp from '../icons/IconArrowUp.vue'
import IconChat from '../icons/IconChat.vue'
import { BTN, BTN_PRIMARY, ERROR } from './styles'

const props = defineProps<{ agentId: number }>()
const router = useRouter()
const store = useSpecialistsStore()
const conversations = ref<SpecialistConversation[]>([])
const loading = ref(true)
const opening = ref(false)
const error = ref<string | null>(null)
const search = ref('')
const others = computed(() => conversations.value.filter(chat => chat.session_id !== store.byId(props.agentId)?.main_session_id))
const filtered = computed(() => others.value.filter(chat => chat.title.toLocaleLowerCase('pt-BR').includes(search.value.toLocaleLowerCase('pt-BR'))))
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
onBeforeUnmount(() => { ticket++ })
onMounted(load)
watch(() => store.changes[props.agentId], load)
</script>

<template>
  <section aria-label="Conversas com o agente" class="agent-conversations">
    <div data-test="agent-main-conversation" class="main-conversation">
      <div class="main-conversation-copy"><span class="conversation-eyebrow">CONTEXTO CONTÍNUO</span><h3>Conversa principal</h3><p>Um lugar para acompanhar o trabalho, discutir decisões e dar o próximo passo com este agente.</p><button type="button" data-test="agent-chat-open" :class="BTN_PRIMARY" :disabled="opening" @click="open()">{{ opening ? 'Abrindo…' : 'Conversar com o agente' }} <IconArrowUp :size="13" class="rotate-45" /></button></div>
      <p class="conversation-note">A skill e os acessos configurados acompanham a conversa. Cada mensagem respeita a fila do agente.</p>
    </div>
    <p v-if="error" role="alert" :class="ERROR">{{ error }} <button type="button" :class="BTN" @click="load">Tentar novamente</button></p>
    <div class="conversation-list-heading"><div><h3>Outros assuntos</h3><p>Contextos separados e conversas das rotinas.</p></div><button type="button" data-test="agent-chat-new" :class="BTN" :disabled="opening" @click="open({ new: true })"><IconPlus :size="13" /> Nova conversa</button></div>
    <input v-if="others.length > 3" v-model="search" data-test="agent-chat-search" type="search" aria-label="Buscar conversa" placeholder="Buscar um assunto…" class="conversation-search" />
    <p v-if="loading" role="status" class="conversation-empty">Carregando conversas…</p>
    <p v-else-if="!conversations.length" data-test="agent-chats-empty" class="conversation-empty">Nenhuma conversa ainda. Comece com uma pergunta ou um pedido.</p>
    <p v-else-if="!filtered.length" class="conversation-empty">{{ search ? 'Nenhum assunto encontrado.' : 'Quando começar outro assunto ou executar uma rotina, a conversa aparece aqui.' }}</p>
    <ul v-else class="conversation-list"><li v-for="chat in filtered" :key="chat.session_id"><button type="button" data-test="agent-chat-row" :disabled="opening" @click="open({ session_id: chat.session_id })"><IconChat :size="15" class="conversation-row-mark" /><span class="conversation-title">{{ chat.title }}</span><span class="conversation-meta">{{ chat.finished ? 'Finalizada' : 'Aberta' }}<span> · {{ formatRunDate(chat.last_activity_at) }}</span></span><IconArrowUp :size="13" class="conversation-arrow rotate-45" /></button></li></ul>
  </section>
</template>
<style scoped>
.agent-conversations { padding:28px 0 48px; }
.main-conversation { display:grid; grid-template-columns:minmax(0,1fr) 220px; align-items:end; gap:36px; padding:28px; border:1px solid var(--color-line); border-radius:12px; background:var(--color-panel); }
.conversation-eyebrow { color:var(--color-fg-subtle); font-size:10px; letter-spacing:.1em; font-weight:500; }
h3 { margin:0; font-size:15px; font-weight:500; letter-spacing:-.015em; }
.main-conversation h3 { margin-top:12px; font-size:23px; letter-spacing:-.03em; }
.main-conversation-copy>p { max-width:54ch; margin:10px 0 22px; color:var(--color-fg-muted); font-size:13px; line-height:1.7; }
.main-conversation-copy>button { display:inline-flex; align-items:center; gap:16px; }
.conversation-note { margin:0; border-left:1px solid var(--color-line); padding-left:20px; color:var(--color-fg-subtle); font-size:11px; line-height:1.8; }
.conversation-list-heading { display:flex; align-items:center; justify-content:space-between; gap:16px; margin:34px 0 16px; }
.conversation-list-heading>button { display:inline-flex; align-items:center; gap:8px; }
.conversation-list-heading p { margin:6px 0 0; color:var(--color-fg-subtle); font-size:12px; }
.conversation-search { width:100%; max-width:360px; margin-bottom:16px; border:1px solid var(--color-line); border-radius:6px; padding:9px 12px; background:var(--color-surface); color:var(--color-fg); font-size:12px; outline-offset:3px; }
.conversation-search:focus-visible { outline:2px solid var(--color-primary); }
.conversation-list { margin:0; padding:0; list-style:none; }
.conversation-list li { border-top:1px solid var(--color-line); }
.conversation-list button { display:flex; width:100%; align-items:center; gap:14px; border:0; border-radius:4px; padding:18px 8px; background:transparent; color:var(--color-fg); text-align:left; cursor:pointer; }
.conversation-list button:hover { background:var(--color-panel); }
.conversation-list button:focus-visible { outline:2px solid var(--color-primary); outline-offset:2px; }
.conversation-title { flex:1; min-width:0; overflow-wrap:anywhere; font-size:13px; }
.conversation-row-mark,.conversation-arrow { color:var(--color-fg-subtle); }
.conversation-meta { color:var(--color-fg-subtle); font-size:11px; }
.conversation-empty { margin:0; border-top:1px solid var(--color-line); padding:28px 0; color:var(--color-fg-subtle); font-size:12px; line-height:1.7; }
button:disabled { opacity:.5; cursor:wait; }
@container (max-width:740px) { .main-conversation { grid-template-columns:1fr; gap:20px; } .conversation-note { border-left:0; border-top:1px solid var(--color-line); padding:16px 0 0; } }
@container (max-width:420px) { .agent-conversations { padding-top:20px; } .main-conversation { padding:20px; } .main-conversation h3 { font-size:21px; } .conversation-list-heading { align-items:flex-start; flex-direction:column; } .conversation-meta>span { display:none; } }
</style>
