<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { useRouter } from 'vue-router'
import { errorMessage, listAgentConversations, openAgentConversation } from '../../../api/http'
import { formatRunDate } from '../../../org'
import { useOrgStore } from '../../../stores/org'
import IconChat from '../../icons/IconChat.vue'
import { BTN, BTN_PRIMARY, ERROR, FIELD } from '../styles'
import type { Conversation } from '../../../types/org'

// The permanent main conversation of the agent, plus the other subjects (separate contexts, and the conversations of
// the runs). Opening any of them goes to `/sessions/:id`.
const props = defineProps<{ agentId: number }>()
const router = useRouter()
const org = useOrgStore()

const conversations = ref<Conversation[]>([])
const loading = ref(true)
const opening = ref(false)
const error = ref<string | null>(null)
const search = ref('')
const headingId = useId()

const agent = computed(() => org.byId(props.agentId))
const others = computed(() => conversations.value.filter((c) => c.session_id !== agent.value?.main_session_id))
const filtered = computed(() => {
  const needle = search.value.toLocaleLowerCase('pt-BR')
  return others.value.filter((c) => c.title.toLocaleLowerCase('pt-BR').includes(needle))
})

let ticket = 0
async function load(): Promise<void> {
  const mine = ++ticket
  try {
    const fresh = await listAgentConversations(props.agentId)
    if (mine === ticket) { conversations.value = fresh; error.value = null }
  } catch (e) {
    if (mine === ticket) error.value = errorMessage(e)
  } finally {
    if (mine === ticket) loading.value = false
  }
}

async function openOther(input: { session_id?: string; new?: boolean }): Promise<void> {
  if (opening.value) return
  opening.value = true
  error.value = null
  try {
    const chat = await openAgentConversation(props.agentId, input)
    await router.push({ name: 'session', params: { id: chat.session_id } })
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    opening.value = false
  }
}

async function openMain(): Promise<void> {
  if (opening.value) return
  opening.value = true
  error.value = null
  try {
    await org.openMain(props.agentId, router)
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    opening.value = false
  }
}

onBeforeUnmount(() => { ticket++ })
onMounted(() => { void load() })
watch(() => org.changes[props.agentId], () => { void load() })
</script>

<template>
  <section aria-label="Conversas com o agente" class="flex min-w-0 flex-col gap-6">
    <div data-test="agent-main-conversation" class="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 rounded-xl border border-line bg-panel p-4">
      <div class="min-w-0">
        <h3 class="m-0 text-base font-medium">Conversa principal</h3>
        <p class="m-0 mt-1 max-w-prose text-sm text-fg-muted">Um lugar contínuo para acompanhar o trabalho, discutir decisões e dar o próximo passo com este agente.</p>
        <p v-if="agent && agent.unseen > 0" data-test="agent-main-unseen" class="m-0 mt-1 text-xs font-semibold text-secondary">{{ agent.unseen }} {{ agent.unseen === 1 ? 'novidade' : 'novidades' }} para você</p>
      </div>
      <button type="button" data-test="agent-chat-open" :class="BTN_PRIMARY" :disabled="opening" @click="openMain">{{ opening ? 'Abrindo…' : 'Conversar com o agente' }}</button>
    </div>

    <p v-if="error" role="alert" :class="[ERROR, 'flex flex-wrap items-center gap-2']">
      <span>{{ error }}</span>
      <button type="button" :class="BTN" @click="load">Tentar de novo</button>
    </p>

    <div class="flex flex-col gap-3">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 :id="headingId" class="m-0 text-base font-medium">Outros assuntos</h3>
          <p class="m-0 mt-0.5 text-xs text-fg-subtle">Contextos separados e conversas das rotinas.</p>
        </div>
        <button type="button" data-test="agent-chat-new" :class="BTN" :disabled="opening" @click="openOther({ new: true })">Nova conversa</button>
      </div>
      <input v-if="others.length > 3" v-model="search" data-test="agent-chat-search" type="search" aria-label="Buscar conversa" placeholder="Buscar um assunto…" :class="[FIELD, 'w-full max-w-sm']" />
      <p v-if="loading" role="status" class="m-0 text-sm text-fg-subtle">Carregando conversas…</p>
      <p v-else-if="!conversations.length" data-test="agent-chats-empty" class="m-0 text-sm text-fg-subtle">Nenhuma conversa ainda. Comece com uma pergunta ou um pedido.</p>
      <p v-else-if="!filtered.length" class="m-0 text-sm text-fg-subtle">{{ search ? 'Nenhum assunto encontrado.' : 'Quando começar outro assunto ou executar uma rotina, a conversa aparece aqui.' }}</p>
      <ul v-else :aria-labelledby="headingId" class="m-0 flex list-none flex-col p-0">
        <li v-for="chat in filtered" :key="chat.session_id" class="border-t border-line first:border-t-0">
          <button
            type="button"
            data-test="agent-chat-row"
            :disabled="opening"
            class="flex w-full cursor-pointer items-center gap-3 rounded border-0 bg-transparent px-2 py-3 text-left text-fg hover:bg-panel focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-wait disabled:opacity-50"
            @click="openOther({ session_id: chat.session_id })"
          >
            <IconChat :size="15" class="shrink-0 text-fg-subtle" />
            <span class="min-w-0 flex-1 text-sm [overflow-wrap:anywhere]">{{ chat.title }}</span>
            <span class="shrink-0 text-xs text-fg-subtle">{{ chat.finished ? 'Finalizada' : 'Aberta' }}<span class="hidden sm:inline"> · {{ formatRunDate(chat.last_activity_at) }}</span></span>
          </button>
        </li>
      </ul>
    </div>
  </section>
</template>
