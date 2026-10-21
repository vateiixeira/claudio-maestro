<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { FitAddon } from '@xterm/addon-fit'
import { Terminal } from '@xterm/xterm'
import '@xterm/xterm/css/xterm.css'
import { errorMessage } from '../../api/http'
import { NO_TERMINAL_CODE, useTerminalStore } from '../../stores/terminal'

const props = defineProps<{ sessionId: string }>()

const store = useTerminalStore()
const state = computed(() => store.sessions[props.sessionId])

// The shell exiting and the socket closing (even before it opened: refused or dropped) both end the terminal.
// A connection still being made is not closed yet.
// 4410: the session has no terminal and the pane only attached; that is an empty state, not an error.
const empty = computed(() => !!state.value?.closed && state.value.closeCode === NO_TERMINAL_CODE && !state.value.exited)
const ended = computed(() => !empty.value && (!!state.value?.exited || !!state.value?.closed))
// 4409: the server refused because the session's folder is gone.
const endedText = computed(() => (state.value?.closeCode === 4409 ? 'A pasta da sessão não existe mais.' : 'O terminal foi encerrado.'))

const screen = ref<HTMLElement | null>(null)
const error = ref<string | null>(null)
const selectionAnchor = ref<{ left: number; top: number } | null>(null)

let term: Terminal | null = null
let fitAddon: FitAddon | null = null
let observer: ResizeObserver | null = null
let stopOutput: (() => void) | null = null
let sent = { cols: 0, rows: 0 }
// xterm answers terminal queries (CSI c, CSI 6n) found in what it is made to write. When that is an old
// replay, the answers are stale and must not reach the shell: input is ignored until the write is done.
let muted = 0

function writeQuiet(target: Terminal, data: string): void {
  muted += 1
  target.write(data, () => {
    muted = Math.max(0, muted - 1)
  })
}

// The app theme's colors; xterm's own defaults stand in when the variable is not defined.
function cssVar(name: string): string | undefined {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || undefined
}

function fitAndReport(): void {
  if (!term || !fitAddon) return
  try {
    fitAddon.fit()
  } catch {
    // The panel is hidden or has no size yet; the next resize tries again.
    return
  }
  if (term.cols === sent.cols && term.rows === sent.rows) return
  sent = { cols: term.cols, rows: term.rows }
  store.resize(props.sessionId, term.cols, term.rows)
}

function updateSelection(): void {
  const current = term
  const el = screen.value
  if (!current || !el || !current.hasSelection()) {
    selectionAnchor.value = null
    return
  }
  const end = current.getSelectionPosition()?.end
  const cellWidth = el.clientWidth / Math.max(current.cols, 1)
  const cellHeight = el.clientHeight / Math.max(current.rows, 1)
  const row = end ? end.y - current.buffer.active.viewportY : current.rows - 1
  const column = end ? end.x : 0
  selectionAnchor.value = {
    left: Math.max(0, Math.min(column * cellWidth, el.clientWidth - 160)),
    top: Math.max(0, Math.min((row + 1) * cellHeight + 4, el.clientHeight - 36)),
  }
}

onMounted(() => {
  const el = screen.value
  if (!el) return
  // Only a gesture (the tab, the header button, a play button) opens a shell; a pane shown just because
  // the tab was remembered only attaches to a terminal that already exists.
  store.connect(props.sessionId, store.takeOpenRequest(props.sessionId))

  const created = new Terminal({
    fontFamily: "'JetBrains Mono', ui-monospace, monospace",
    fontSize: 13,
    cursorBlink: true,
    scrollback: 5000,
    theme: {
      background: cssVar('--color-panel'),
      foreground: cssVar('--color-fg'),
      cursor: cssVar('--color-fg'),
      selectionBackground: cssVar('--color-line-strong'),
    },
  })
  term = created
  fitAddon = new FitAddon()
  created.loadAddon(fitAddon)
  created.open(el)
  fitAndReport()

  const buffer = state.value?.buffer ?? ''
  if (buffer) writeQuiet(created, buffer)
  stopOutput = store.onOutput(props.sessionId, (data, reset) => {
    if (reset) {
      created.reset()
      writeQuiet(created, data)
    } else {
      created.write(data)
    }
  })
  created.onData((data) => {
    if (muted > 0) return
    store.sendInput(props.sessionId, data)
  })
  created.onSelectionChange(updateSelection)

  if (typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(fitAndReport)
    observer.observe(el)
  }
})

// Unmounting only drops the screen: the connection and its buffer stay with the session.
onBeforeUnmount(() => {
  observer?.disconnect()
  stopOutput?.()
  term?.dispose()
  term = null
  fitAddon = null
})

function visibleScreen(): string {
  if (!term) return ''
  const { viewportY } = term.buffer.active
  const lines: string[] = []
  for (let i = viewportY; i < viewportY + term.rows; i += 1) {
    lines.push(term.buffer.active.getLine(i)?.translateToString(true).trimEnd() ?? '')
  }
  return lines.join('\n').trimEnd()
}

function attachScreen(): void {
  store.attach(props.sessionId, visibleScreen())
}

function attachSelection(): void {
  if (!term) return
  store.attach(props.sessionId, term.getSelection())
  term.clearSelection()
  selectionAnchor.value = null
}

async function closeTerminal(): Promise<void> {
  error.value = null
  try {
    await store.close(props.sessionId)
  } catch (e) {
    error.value = errorMessage(e)
  }
}

// A click on "Abrir de novo" / "Abrir terminal": a gesture, so the new connection starts the shell.
// The store sends the last known size to every new connection.
function reopen(): void {
  error.value = null
  store.disconnect(props.sessionId)
  store.connect(props.sessionId, true)
}

// Something asked for this session's terminal (header button, play) while the pane is already up: make sure
// the connection is one that may open the shell.
watch(
  () => store.panelRequest,
  (request) => {
    if (!request || request.sessionId !== props.sessionId) return
    store.takeOpenRequest(props.sessionId)
    if (state.value?.closed) reopen()
    // Not closed yet: a socket that only attaches and is still connecting would meet 4410 right after;
    // `connect` with open replaces it (and leaves a live or already opening one alone).
    else store.connect(props.sessionId, true)
  },
)
</script>

<template>
  <section data-test="terminal-pane" aria-label="Terminal da sessão" class="flex h-full min-h-0 flex-col bg-panel">
    <div class="flex shrink-0 items-center gap-2 border-b border-line px-3 py-2">
      <button
        type="button"
        data-test="terminal-attach-screen"
        class="h-7 rounded-md border border-line-strong px-2.5 text-xs font-medium text-fg hover:bg-card focus-visible:outline-2 focus-visible:outline-primary"
        @click="attachScreen"
      >Anexar tela</button>
      <span class="grow" />
      <button
        type="button"
        data-test="terminal-close"
        :disabled="ended || empty"
        class="h-7 rounded-md border border-line-strong px-2.5 text-xs font-medium text-fg hover:bg-card focus-visible:outline-2 focus-visible:outline-primary disabled:opacity-40"
        @click="closeTerminal"
      >Encerrar</button>
    </div>
    <p v-if="error" data-test="terminal-error" role="alert" class="m-0 shrink-0 px-3 py-2 text-xs text-diff-del-fg">{{ error }}</p>
    <div class="relative min-h-0 grow overflow-hidden">
      <div ref="screen" data-test="terminal-screen" class="absolute inset-0 overflow-hidden p-2" />
      <button
        v-if="selectionAnchor"
        type="button"
        data-test="terminal-attach-selection"
        class="absolute z-10 h-7 rounded-md border border-line-strong bg-elevated px-2.5 text-xs font-medium whitespace-nowrap text-fg shadow-lg hover:bg-card focus-visible:outline-2 focus-visible:outline-primary"
        :style="{ left: `${selectionAnchor.left}px`, top: `${selectionAnchor.top}px` }"
        @mousedown.prevent
        @click="attachSelection"
      >Anexar à mensagem</button>
      <div v-if="empty" data-test="terminal-empty" role="status" class="absolute inset-0 z-20 flex flex-col items-center justify-center gap-3 bg-panel p-4 text-center">
        <p class="m-0 text-sm text-fg-muted">Nenhum terminal aberto nesta sessão.</p>
        <button
          type="button"
          data-test="terminal-open"
          class="h-8 rounded-md border border-line-strong px-3 text-sm font-medium text-fg hover:bg-card focus-visible:outline-2 focus-visible:outline-primary"
          @click="reopen"
        >Abrir terminal</button>
      </div>
    </div>
    <div v-if="ended" data-test="terminal-ended" role="status" class="flex shrink-0 items-center gap-3 border-t border-line px-3 py-2 text-xs text-fg-muted">
      <span class="grow">{{ endedText }}</span>
      <button
        type="button"
        data-test="terminal-reopen"
        class="h-7 rounded-md border border-line-strong px-2.5 text-xs font-medium text-fg hover:bg-card focus-visible:outline-2 focus-visible:outline-primary"
        @click="reopen"
      >Abrir de novo</button>
    </div>
  </section>
</template>
