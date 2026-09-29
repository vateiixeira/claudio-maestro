<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { errorMessage } from '../api/http'
import { useEventSocket } from '../api/socket'
import SessionStateIcon from '../components/SessionStateIcon.vue'
import ConversationBlock from '../components/conversation/ConversationBlock.vue'
import MessageComposer from '../components/conversation/MessageComposer.vue'
import PermissionCard from '../components/conversation/PermissionCard.vue'
import { sessionStateLabels } from '../sessionState'
import { useConversationStore } from '../stores/conversation'
import { useProjectsStore } from '../stores/projects'
import type { ConversationItem } from '../types/conversation'

const props = defineProps<{ id: string }>()

const conversations = useConversationStore()
const projects = useProjectsStore()
const socket = useEventSocket()

const loadError = ref<string | null>(null)
const conv = computed(() => conversations.get(props.id))
const project = computed(() => (conv.value?.projectId != null ? projects.byId(conv.value.projectId) : undefined))

async function reload() {
  try {
    await conversations.load(props.id)
    loadError.value = null
  } catch (e) {
    loadError.value = errorMessage(e)
  }
}

let offs: Array<() => void> = []
watch(
  () => props.id,
  (id) => {
    offs.forEach((off) => off())
    offs = [
      socket.onSession(id, (event) => conversations.receive(event)),
      socket.onReconnect(() => void reload()),
    ]
    loadError.value = null
    void reload()
  },
  { immediate: true },
)
onBeforeUnmount(() => offs.forEach((off) => off()))

// Items with a parent tool are shown indented under that tool.
const layout = computed(() => {
  const items = conv.value?.items ?? []
  const toolIds = new Set(items.flatMap((i) => (i.type === 'tool' ? [i.tool_use_id] : [])))
  const children = new Map<string, ConversationItem[]>()
  const top: ConversationItem[] = []
  for (const item of items) {
    const parent = 'parent_tool_use_id' in item ? item.parent_tool_use_id : null
    if (parent && toolIds.has(parent)) {
      const list = children.get(parent) ?? []
      list.push(item)
      children.set(parent, list)
    } else top.push(item)
  }
  const rows: Array<{ item: ConversationItem; depth: number }> = []
  const visit = (item: ConversationItem, depth: number) => {
    rows.push({ item, depth })
    if (item.type === 'tool') children.get(item.tool_use_id)?.forEach((child) => visit(child, depth + 1))
  }
  top.forEach((item) => visit(item, 'parent_tool_use_id' in item && item.parent_tool_use_id ? 1 : 0))
  return rows
})

const footer = computed(() => {
  const result = conv.value?.lastResult
  if (!result) return null
  const parts: string[] = []
  if (result.duration_ms != null) {
    parts.push(`${(result.duration_ms / 1000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} s`)
  }
  if (result.total_cost_usd != null) {
    parts.push(`US$ ${result.total_cost_usd.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`)
  }
  if (result.is_error) parts.push('terminou com erro')
  return parts.length ? `Último turno: ${parts.join(' · ')}` : null
})

// Follows the end of the conversation only while the user is already there.
const scroller = ref<HTMLElement | null>(null)
const atBottom = ref(true)
function onScroll() {
  const el = scroller.value
  if (!el) return
  atBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 48
}
watch(
  () => [conv.value?.seq, conv.value?.items.length, conv.value?.prompts.length],
  async () => {
    if (!atBottom.value) return
    await nextTick()
    const el = scroller.value
    if (el) el.scrollTop = el.scrollHeight
  },
)

function resolvePrompt(promptId: string) {
  conversations.resolvePrompt(props.id, promptId)
}
</script>

<template>
  <section :aria-label="conv ? `Sessão: ${conv.title}` : 'Sessão'" class="flex h-full min-w-0 flex-col">
    <template v-if="conv">
      <header class="flex flex-col gap-2 border-b border-line px-4 pt-4 pb-3">
        <div class="flex items-center gap-2">
          <RouterLink
            v-if="project"
            :to="{ name: 'project', params: { id: project.id } }"
            class="flex min-w-0 grow items-center gap-2 text-xs text-fg-muted no-underline hover:text-fg"
          >
            <span class="size-2.5 shrink-0 rounded-[3px]" :style="{ backgroundColor: project.color }" />
            <span class="truncate">{{ project.name }}</span>
          </RouterLink>
          <span v-else class="grow" />
          <span
            data-test="session-state"
            class="flex items-center gap-1.5 rounded-full border px-2.5 py-[3px] text-xs font-semibold"
            :class="{
              'border-primary/40 bg-primary/10 text-primary-soft': conv.state === 'running' || conv.state === 'connecting',
              'border-secondary/40 bg-secondary/10 text-secondary': conv.state === 'awaiting_decision' || conv.state === 'error',
              'border-line-strong bg-card text-fg-muted': conv.state === 'idle' || conv.state === 'closed',
            }"
          >
            <SessionStateIcon :state="conv.state" />
            {{ sessionStateLabels[conv.state] }}
          </span>
        </div>
        <h2 class="m-0 text-lg font-semibold">{{ conv.title }}</h2>
      </header>

      <div ref="scroller" class="min-h-0 grow overflow-y-auto" @scroll="onScroll">
        <div class="flex flex-col gap-3 p-4">
          <p v-if="layout.length === 0" class="m-0 py-8 text-center text-sm text-fg-muted">
            Nenhuma mensagem ainda. Escreva abaixo para começar.
          </p>
          <div
            v-for="row in layout"
            :key="row.item.id"
            class="flex min-w-0 flex-col"
            :class="{ 'border-l border-line pl-4': row.depth > 0 }"
            :style="row.depth > 1 ? { marginLeft: `${(row.depth - 1) * 16}px` } : undefined"
          >
            <ConversationBlock :item="row.item" />
          </div>
          <PermissionCard
            v-for="prompt in conv.prompts"
            :key="prompt.prompt_id"
            :session-id="conv.sessionId"
            :prompt="prompt"
            @resolved="resolvePrompt(prompt.prompt_id)"
          />
          <p v-if="footer" data-test="turn-footer" class="m-0 font-mono text-xs text-fg-muted">{{ footer }}</p>
        </div>
      </div>

      <div class="flex flex-col gap-2.5 border-t border-line px-4 pt-3 pb-3.5">
        <p
          v-if="conv.state === 'error'"
          data-test="session-error"
          role="alert"
          class="m-0 rounded-md border border-diff-del-fg/40 bg-diff-del-bg px-3 py-2 text-sm text-diff-del-fg"
        >
          {{ conv.error || 'A sessão parou com erro.' }} Você pode enviar de novo.
        </p>
        <p v-if="loadError" role="alert" class="m-0 text-sm text-secondary-soft">{{ loadError }}</p>
        <MessageComposer :session-id="conv.sessionId" :state="conv.state" />
      </div>
    </template>
    <div v-else class="px-10 py-8">
      <p v-if="loadError" role="alert" class="text-fg-muted">
        {{ loadError }}
        <RouterLink to="/" class="text-primary-soft hover:underline">Voltar ao início</RouterLink>
      </p>
      <p v-else class="text-fg-muted">Carregando…</p>
    </div>
  </section>
</template>
