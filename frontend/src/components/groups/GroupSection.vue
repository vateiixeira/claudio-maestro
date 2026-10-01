<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import type { RouteLocationRaw } from 'vue-router'
import ConversationRow from '../conversation/ConversationRow.vue'
import { errorMessage } from '../../api/http'
import { isActive } from '../../groupList'
import { useGroupsStore } from '../../stores/groups'
import { useNewConversationStore } from '../../stores/newConversation'
import type { Session, SessionGroup } from '../../types/api'

const props = defineProps<{
  group: SessionGroup
  sessions: Session[]
  available: boolean
  rowTarget?: (sessionId: string) => RouteLocationRaw | undefined
  activeId?: string | null
}>()
const emit = defineEmits<{ error: [message: string] }>()

const groups = useGroupsStore()
const newConversation = useNewConversationStore()

const open = ref(true)
const active = computed(() => props.sessions.filter(isActive).length)
const countText = computed(() => {
  const n = props.sessions.length
  if (n === 0) return 'Nenhuma conversa'
  return `${n} ${n === 1 ? 'conversa' : 'conversas'} · ${active.value} ${active.value === 1 ? 'ativa' : 'ativas'}`
})
const removeText = computed(() => {
  const n = props.sessions.length
  if (n === 0) return 'O agrupador está vazio.'
  if (n === 1) return 'A conversa volta a ficar solta; nenhuma é apagada.'
  return `As ${n} conversas voltam a ficar soltas; nenhuma é apagada.`
})

const renaming = ref(false)
const renameValue = ref('')
const renameError = ref<string | null>(null)
const renameInput = ref<HTMLInputElement | null>(null)
async function startRename() {
  renaming.value = true
  confirming.value = false
  renameValue.value = props.group.name
  renameError.value = null
  await nextTick()
  renameInput.value?.select()
}
async function saveRename() {
  renameError.value = null
  try {
    await groups.rename(props.group.id, renameValue.value)
    renaming.value = false
  } catch (e) {
    renameError.value = errorMessage(e)
  }
}

const confirming = ref(false)
const removing = ref(false)
const removeButton = ref<HTMLButtonElement | null>(null)
const cancelButton = ref<HTMLButtonElement | null>(null)
async function askRemove() {
  confirming.value = true
  renaming.value = false
  await nextTick()
  cancelButton.value?.focus()
}
async function cancelRemove() {
  confirming.value = false
  await nextTick()
  removeButton.value?.focus()
}
async function remove() {
  removing.value = true
  try {
    await groups.remove(props.group.id)
  } catch (e) {
    emit('error', errorMessage(e))
    confirming.value = false
  } finally {
    removing.value = false
  }
}
</script>

<template>
  <section data-test="group-section" :aria-label="group.name" class="flex flex-col rounded-lg border border-line bg-panel">
    <div class="flex min-h-11 flex-wrap items-center gap-2 px-2">
      <button type="button" data-test="group-toggle" :aria-expanded="open" :aria-label="open ? `Recolher ${group.name}` : `Expandir ${group.name}`" class="flex size-8 items-center justify-center rounded-md text-fg-muted hover:bg-card" @click="open = !open">
        <span aria-hidden="true" class="inline-block transition-transform" :class="open ? 'rotate-90' : ''">›</span>
      </button>
      <template v-if="renaming">
        <input ref="renameInput" v-model="renameValue" data-test="group-rename-input" aria-label="Novo nome do agrupador" maxlength="80" class="h-8 grow rounded-md border border-line-strong bg-elevated px-2 text-sm text-fg outline-none focus:border-fg-muted" @keydown.enter.prevent="saveRename" @keydown.esc.prevent="renaming = false" />
      </template>
      <template v-else>
        <span data-test="group-name" class="min-w-0 truncate font-semibold">{{ group.name }}</span>
        <span data-test="group-count" class="text-xs text-fg-subtle">{{ countText }}</span>
      </template>
      <span class="grow" />
      <button type="button" data-test="group-new-session" :disabled="!available" class="h-8 rounded-md px-2 text-xs text-fg-muted hover:bg-card hover:text-fg disabled:opacity-40" @click="newConversation.open(group.project_id, group.id)">＋ Conversa</button>
      <button type="button" data-test="group-rename" class="h-8 rounded-md px-2 text-xs text-fg-muted hover:bg-card hover:text-fg" @click="startRename">Renomear</button>
      <button ref="removeButton" type="button" data-test="group-remove" class="h-8 rounded-md px-2 text-xs text-fg-muted hover:bg-card hover:text-fg" @click="askRemove">Remover</button>
    </div>
    <p v-if="renameError" role="alert" class="m-0 px-4 pb-2 text-sm text-secondary-soft">{{ renameError }}</p>
    <div
      v-if="confirming"
      data-test="group-confirm-remove"
      role="alertdialog"
      :aria-label="`Remover o agrupador ${group.name}?`"
      class="mx-2 mb-2 flex flex-col gap-2 rounded-lg border border-secondary/60 bg-card px-4 py-3"
      @keydown.esc.prevent="cancelRemove"
    >
      <p class="m-0 text-sm font-semibold">Remover o agrupador {{ group.name }}?</p>
      <p class="m-0 text-sm text-fg-muted">{{ removeText }}</p>
      <div class="flex gap-2">
        <button type="button" data-test="group-confirm-ok" :disabled="removing" class="h-9 rounded-lg bg-secondary px-3 text-sm font-semibold text-secondary-fg hover:bg-secondary-soft disabled:opacity-40" @click="remove">{{ removing ? 'Removendo…' : 'Remover agrupador' }}</button>
        <button ref="cancelButton" type="button" data-test="group-confirm-cancel" class="h-9 rounded-lg border border-line-strong px-3 text-sm text-fg hover:bg-elevated" @click="cancelRemove">Cancelar</button>
      </div>
    </div>
    <div v-if="open && sessions.length" class="flex flex-col px-1 pb-1">
      <ConversationRow
        v-for="s in sessions"
        :key="s.session_id"
        :session="s"
        :to="rowTarget?.(s.session_id)"
        :active="activeId != null && s.session_id === activeId"
        @error="emit('error', $event)"
      />
    </div>
  </section>
</template>
