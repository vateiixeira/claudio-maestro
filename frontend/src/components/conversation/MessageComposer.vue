<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { errorMessage, interruptSession, sendMessage } from '../../api/http'
import { useDictation } from '../../conversation/dictation'
import { type DraftImage, attachImages, base64Of, filesFrom, formatSize } from '../../conversation/images'
import { takePendingDraft } from '../../conversation/pendingDrafts'
import { useComposerSuggestions } from '../../conversation/useComposerSuggestions'
import { rememberSentImages } from '../../conversation/localImages'
import { useConversationStore } from '../../stores/conversation'
import type { SessionState } from '../../types/api'
import MentionMirror from './MentionMirror.vue'
import SuggestionMenu from './SuggestionMenu.vue'

// `blockedReason`: why sending is not possible now (e.g. the project folder is gone).
const props = defineProps<{ sessionId: string; state: SessionState; blockedReason?: string | null }>()

const pendingDraft = takePendingDraft(props.sessionId)
const text = ref(pendingDraft?.text ?? '')
const sending = ref(false)
const interrupting = ref(false)
const error = ref<string | null>(pendingDraft?.error ?? null)
const textarea = ref<HTMLTextAreaElement | null>(null)

const images = ref<DraftImage[]>(pendingDraft?.images ?? [])
const canSend = computed(() => !sending.value && !props.blockedReason && (text.value.trim() !== '' || images.value.length > 0))

/** Attaches image files after checking format, size and count. Used by paste and drop. */
async function addFiles(files: File[]) {
  const { error: problem } = await attachImages(() => images.value, files)
  error.value = problem
}
defineExpose({ addFiles })

function removeImage(id: number) {
  images.value = images.value.filter((i) => i.id !== id)
}

function onPaste(event: ClipboardEvent) {
  const files = filesFrom(event.clipboardData)
  if (!files.length) return
  event.preventDefault()
  void addFiles(files)
}

function onDrop(event: DragEvent) {
  const files = filesFrom(event.dataTransfer)
  if (!files.length) return
  event.preventDefault()
  event.stopPropagation()
  void addFiles(files)
}

const suggestions = useComposerSuggestions({
  textarea,
  text,
  scope: () => ({ sessionId: props.sessionId }),
  onApplied: resize,
})

const dictation = useDictation({
  begin() {
    suggestions.close()
    const el = textarea.value
    return { text: text.value, cursor: el?.selectionStart ?? text.value.length }
  },
  update(value, cursor) {
    text.value = value
    const el = textarea.value
    if (el) {
      el.value = value
      el.setSelectionRange(cursor, cursor)
    }
    nextTick(resize)
  },
})

// The highlight layer behind the field follows its scroll.
const scrollTop = ref(0)
function onScroll() {
  scrollTop.value = textarea.value?.scrollTop ?? 0
}

const busy = computed(() => props.state === 'running' || props.state === 'awaiting_decision')

// Grows with the text up to 40% of the column, then scrolls.
function resize() {
  const el = textarea.value
  if (!el) return
  const column = el.closest('section') as HTMLElement | null
  const max = (column?.clientHeight || window.innerHeight) * 0.4
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, max)}px`
  el.style.overflowY = el.scrollHeight > max ? 'auto' : 'hidden'
}

// Typing while dictating stops the dictation, so it does not overwrite what was typed.
function onInput() {
  if (dictation.recording.value) dictation.stop()
  resize()
  suggestions.refresh()
}

// setSelectionRange (used by the dictation to place the cursor) fires `select`, so the
// event is ignored while recording: dictated text must never open the menus.
function onSelect() {
  if (dictation.recording.value) return
  suggestions.refresh()
}

function insertNewline() {
  const el = textarea.value
  if (!el) return
  const start = el.selectionStart ?? text.value.length
  const end = el.selectionEnd ?? start
  text.value = text.value.slice(0, start) + '\n' + text.value.slice(end)
  el.value = text.value
  el.setSelectionRange(start + 1, start + 1)
  nextTick(resize)
}

function onKeydown(event: KeyboardEvent) {
  if (suggestions.onKeydown(event)) return
  if (event.key !== 'Enter' || event.isComposing || event.keyCode === 229) return
  if (event.shiftKey) return // browser inserts the line break
  event.preventDefault()
  if (event.ctrlKey || event.metaKey || event.altKey) insertNewline()
  else void send()
}

async function send() {
  const message = text.value
  // A copy: an image that finishes reading while the request is out is not part of this message.
  const attached = [...images.value]
  if (!canSend.value) return
  suggestions.close()
  if (dictation.recording.value) dictation.stop()
  sending.value = true
  error.value = null
  // Registered before the request: the user item may arrive over the socket first.
  const forget = attached.length ? rememberSentImages(props.sessionId, attached.map((i) => ({ url: i.url, mediaType: i.mediaType, size: i.size }))) : () => {}
  try {
    const result = await sendMessage(
      props.sessionId,
      message,
      attached.map((i) => ({ media_type: i.mediaType, data: base64Of(i) })),
    )
    if (result?.external_activity) useConversationStore().noteExternalActivity(props.sessionId)
    // Only clear if the user did not keep typing meanwhile.
    if (text.value === message) text.value = ''
    images.value = images.value.filter((i) => !attached.includes(i))
    nextTick(resize)
  } catch (e) {
    forget()
    error.value = errorMessage(e)
  } finally {
    sending.value = false
  }
}

async function interrupt() {
  interrupting.value = true
  error.value = null
  try {
    await interruptSession(props.sessionId)
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    interrupting.value = false
  }
}
</script>

<template>
  <div class="flex flex-col gap-2.5" @dragover.prevent @drop="onDrop">
    <p v-if="blockedReason" :id="`blocked-${sessionId}`" class="m-0 text-sm text-fg-muted">{{ blockedReason }}</p>
    <p v-if="error" role="alert" class="m-0 text-sm text-diff-del-fg">{{ error }}</p>
    <p v-else-if="dictation.error.value" role="alert" class="m-0 text-sm text-diff-del-fg">{{ dictation.error.value }}</p>
    <div v-if="images.length" class="flex flex-wrap gap-2">
      <div
        v-for="image in images"
        :key="image.id"
        data-test="attachment-draft"
        class="flex items-center gap-2.5 rounded-lg border border-line-strong bg-card p-1.5"
      >
        <img :src="image.url" alt="" class="size-11 rounded-md bg-line object-cover" />
        <div class="flex min-w-0 flex-col">
          <span class="max-w-40 truncate text-[13px] font-medium">{{ image.name }}</span>
          <span class="text-xs text-fg-muted">{{ formatSize(image.size) }}</span>
        </div>
        <button
          type="button"
          :aria-label="`Remover imagem ${image.name}`"
          class="flex size-11 cursor-pointer items-center justify-center rounded-md border-none bg-transparent text-fg-muted hover:bg-elevated hover:text-fg"
          @click="removeImage(image.id)"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><line x1="6" y1="6" x2="18" y2="18" /><line x1="18" y1="6" x2="6" y2="18" /></svg>
        </button>
      </div>
    </div>
    <div class="flex items-end gap-2">
      <label :for="`msg-${sessionId}`" class="sr-only">Mensagem para a sessão</label>
      <div class="relative min-w-0 grow rounded-lg bg-panel">
        <MentionMirror
          :text="text"
          :mentions="suggestions.mentions.value"
          :hint="suggestions.argumentHint.value"
          :scroll-top="scrollTop"
          class="rounded-lg border border-transparent px-3.5 py-[11px] font-sans text-sm leading-normal"
        />
        <textarea
          :id="`msg-${sessionId}`"
          ref="textarea"
          v-model="text"
          rows="1"
          placeholder="Mensagem (Ctrl+V cola imagens)"
          role="combobox"
          aria-autocomplete="list"
          :aria-expanded="suggestions.isOpen.value"
          :aria-controls="suggestions.menuId"
          :aria-activedescendant="suggestions.isOpen.value && suggestions.items.value.length ? suggestions.optionId(suggestions.active.value) : undefined"
          class="relative block min-h-11 w-full resize-none overflow-hidden rounded-lg border border-line-strong bg-transparent px-3.5 py-[11px] font-sans text-sm leading-normal text-fg outline-none focus:border-fg-muted"
          @input="onInput"
          @scroll="onScroll"
          @keydown="onKeydown"
          @keyup="suggestions.refresh()"
          @click="suggestions.refresh()"
          @select="onSelect"
          @blur="suggestions.onBlur()"
          @paste="onPaste"
        />
        <SuggestionMenu
          v-if="suggestions.isOpen.value && suggestions.kind.value"
          :id="suggestions.menuId"
          :items="suggestions.items.value"
          :active="suggestions.active.value"
          :status="suggestions.status.value"
          :error="suggestions.error.value"
          :kind="suggestions.kind.value"
          :option-id="suggestions.optionId"
          @choose="(i) => suggestions.choose(i, 'click')"
          @hover="(i) => (suggestions.active.value = i)"
        />
      </div>
      <button
        v-if="dictation.supported"
        type="button"
        data-test="dictate"
        :aria-label="dictation.recording.value ? 'Parar ditado' : 'Ditar mensagem'"
        :aria-pressed="dictation.recording.value"
        :title="dictation.recording.value ? 'Parar ditado' : 'Ditar mensagem'"
        class="flex size-11 shrink-0 cursor-pointer items-center justify-center rounded-lg border"
        :class="dictation.recording.value ? 'border-secondary/60 bg-secondary/10 text-secondary' : 'border-line-strong bg-transparent text-fg-muted hover:text-fg'"
        @click="dictation.toggle"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg>
      </button>
      <button
        v-if="busy"
        type="button"
        data-test="interrupt"
        class="flex h-11 cursor-pointer items-center gap-2 rounded-lg border border-line-strong bg-elevated px-3.5 text-sm font-medium text-fg disabled:opacity-60"
        :disabled="interrupting"
        @click="interrupt"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="2" /></svg>
        Interromper
      </button>
      <button
        type="button"
        data-test="send"
        class="h-11 cursor-pointer rounded-lg border-none bg-primary px-4 text-sm font-semibold text-primary-fg disabled:cursor-default disabled:opacity-50"
        :disabled="!canSend"
        :title="blockedReason || undefined"
        :aria-describedby="blockedReason ? `blocked-${sessionId}` : undefined"
        @click="send"
      >
        Enviar
      </button>
    </div>
    <div class="flex flex-wrap items-center gap-2">
      <slot name="controls" />
      <span v-if="dictation.recording.value" data-test="recording" role="status" class="flex items-center gap-1.5 text-xs text-secondary">
        <span class="size-2 animate-pulse rounded-full bg-secondary" aria-hidden="true" />Gravando… clique no microfone para parar
      </span>
      <span class="ml-auto font-mono text-xs text-fg-muted">Enter envia · Ctrl+Enter quebra linha</span>
    </div>
  </div>
</template>
