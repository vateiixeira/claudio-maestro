<script setup lang="ts">
import { computed, nextTick, ref, useId } from 'vue'
import { errorMessage } from '../../api/http'
import { nextMondayAt9, tomorrowAt9 } from '../../conversation/marks'
import { useSessionsStore } from '../../stores/sessions'
import type { Session, SessionMark } from '../../types/api'

defineOptions({ name: 'MarkMenu' })
const props = defineProps<{ session: Session }>()
const emit = defineEmits<{ done: []; error: [message: string] }>()
const sessions = useSessionsStore()
const editing = ref<'date' | 'note' | null>(null)
const date = ref('')
const note = ref('')
const field = ref<HTMLInputElement | null>(null)
const menu = ref<HTMLElement | null>(null)
const holdTitleId = useId()

// Which "Em espera" option is the current one; null when the session is not on hold.
const holdChoice = computed<'tomorrow' | 'monday' | 'custom' | 'none' | null>(() => {
  if (props.session.mark !== 'on_hold') return null
  const until = props.session.mark_until
  if (!until) return 'none'
  const now = new Date()
  if (until === tomorrowAt9(now)) return 'tomorrow'
  if (until === nextMondayAt9(now)) return 'monday'
  return 'custom'
})

async function run(action: () => Promise<void>) {
  try {
    await action()
    emit('done')
  } catch (e) {
    emit('error', errorMessage(e))
  }
}
// Without `extra` the store is called with two arguments only (clearing a mark).
const mark = (value: SessionMark | null, extra?: { mark_note?: string | null; mark_until?: number | null }) =>
  run(() => (extra ? sessions.setMark(props.session.session_id, value, extra) : sessions.setMark(props.session.session_id, value)))
const onHold = (until: number | null) => mark('on_hold', { mark_until: until })

async function edit(kind: 'date' | 'note') {
  editing.value = kind
  if (kind === 'date') {
    const d = new Date(tomorrowAt9(new Date()) * 1000)
    const pad = (n: number) => String(n).padStart(2, '0')
    date.value = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T09:00`
  } else {
    note.value = props.session.mark_note ?? ''
  }
  await nextTick()
  field.value?.focus()
}
function saveDate() {
  const when = new Date(date.value)
  if (Number.isNaN(when.getTime())) return
  void onHold(Math.floor(when.getTime() / 1000))
}
function saveNote() {
  void mark('blocked', { mark_note: note.value.trim() || null })
}
// Arrows move between the items (wrapping); Home and End jump. The date and note fields keep their own keys.
function onKeydown(event: KeyboardEvent) {
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
  const items = [...(menu.value?.querySelectorAll<HTMLElement>('[role^="menuitem"]') ?? [])]
  const at = items.indexOf(event.target as HTMLElement)
  if (at < 0) return
  event.preventDefault()
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (at + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length
  items[next]?.focus()
}
const item = 'w-full px-3 py-1.5 text-left text-sm hover:bg-elevated focus:bg-elevated focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-fg-muted'
</script>

<template>
  <div ref="menu" role="menu" aria-label="Marcar sessão" class="flex w-60 flex-col py-1" @keydown="onKeydown">
    <div role="group" :aria-labelledby="holdTitleId">
      <p :id="holdTitleId" class="m-0 px-3 pt-1 pb-0.5 font-mono text-[0.6875rem] tracking-[0.08em] text-fg-subtle uppercase">Em espera</p>
      <button type="button" role="menuitemradio" data-test="mark-tomorrow" :aria-checked="holdChoice === 'tomorrow'" :class="item" @click="onHold(tomorrowAt9(new Date()))">Amanhã às 9h</button>
      <button type="button" role="menuitemradio" data-test="mark-monday" :aria-checked="holdChoice === 'monday'" :class="item" @click="onHold(nextMondayAt9(new Date()))">Próxima segunda às 9h</button>
      <button type="button" role="menuitemradio" data-test="mark-pick-date" :aria-checked="holdChoice === 'custom'" :class="item" @click="edit('date')">Escolher data…</button>
      <div v-if="editing === 'date'" role="none" class="flex gap-1.5 px-3 py-1.5">
        <input ref="field" v-model="date" data-test="mark-date-input" type="datetime-local" aria-label="Data em que a sessão volta" class="h-8 min-w-0 grow rounded-md border border-line-strong bg-elevated px-2 text-sm text-fg" @keydown.enter.prevent="saveDate" />
        <button type="button" data-test="mark-date-save" class="h-8 rounded-md border border-line-strong px-2 text-sm hover:bg-card" @click="saveDate">Salvar</button>
      </div>
      <button type="button" role="menuitemradio" data-test="mark-no-date" :aria-checked="holdChoice === 'none'" :class="item" @click="onHold(null)">Sem data</button>
    </div>
    <div role="separator" class="my-1 border-t border-line" />
    <button type="button" role="menuitemradio" data-test="mark-blocked" :aria-checked="session.mark === 'blocked'" :class="item" @click="edit('note')">Bloqueada…</button>
    <div v-if="editing === 'note'" role="none" class="flex gap-1.5 px-3 py-1.5">
      <input ref="field" v-model="note" data-test="mark-note-input" maxlength="80" placeholder="Esperando o quê? (opcional)" aria-label="Nota do bloqueio" class="h-8 min-w-0 grow rounded-md border border-line-strong bg-elevated px-2 text-sm text-fg" @keydown.enter.prevent="saveNote" />
      <button type="button" data-test="mark-note-save" class="h-8 rounded-md border border-line-strong px-2 text-sm hover:bg-card" @click="saveNote">Salvar</button>
    </div>
    <button type="button" role="menuitemradio" data-test="mark-review" :aria-checked="session.mark === 'review'" :class="item" @click="mark('review')">Para revisar</button>
    <button v-if="session.mark" type="button" role="menuitem" data-test="mark-clear" :class="item" @click="mark(null)">Remover marcação</button>
    <div role="separator" class="my-1 border-t border-line" />
    <button type="button" role="menuitemcheckbox" data-test="mark-priority" :aria-checked="!!session.priority" :class="item" @click="run(() => sessions.setPriority(session.session_id, !session.priority))">
      {{ session.priority ? 'Tirar prioridade' : 'Prioridade' }}
    </button>
  </div>
</template>
