import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ApiError, closeTerminal, runInTerminal } from '../api/http'
import { TerminalSocket, type TerminalFrame } from '../api/terminalSocket'

/** What the store keeps of one session's terminal. */
export interface TerminalSession {
  connected: boolean
  busy: boolean
  exited: boolean
  buffer: string
}

export type RunState = 'starting' | 'running' | 'sent' | 'interrupted' | 'failed' | 'busy'

/** One click on a play button, followed until the output is sent to Claude. */
export interface TerminalRunInfo {
  state: RunState
  exitCode: number | null
  blockKey: string
}

type RunFrame = Extract<TerminalFrame, { type: 'run' }>

/** Called with new output. `reset` is true when `data` is a replay that replaces everything shown. */
export type OutputListener = (data: string, reset: boolean) => void

/** The most the buffer keeps, the same limit the server uses for the replay. */
export const BUFFER_LIMIT = 262_144
/** How long a refused run (terminal busy) shows "busy" before the play button is idle again. */
export const BUSY_RESET_MS = 2500

function emptySession(): TerminalSession {
  return { connected: false, busy: false, exited: false, buffer: '' }
}

function clip(text: string): string {
  return text.length > BUFFER_LIMIT ? text.slice(text.length - BUFFER_LIMIT) : text
}

/** The terminal of each session: connection, output, play-button runs and snippets attached to the next message. */
export const useTerminalStore = defineStore('terminal', () => {
  const sessions = ref<Record<string, TerminalSession>>({})
  const runs = ref<Record<string, TerminalRunInfo>>({})
  const attachments = ref<Record<string, string[]>>({})
  // Changes whenever something asks for the terminal panel to open; `seq` makes repeated asks distinct.
  const panelRequest = ref<{ sessionId: string; seq: number } | null>(null)

  const sockets = new Map<string, TerminalSocket>()
  const listeners = new Map<string, Set<OutputListener>>()
  // run_id -> block, and the run_id each block is waiting for, so an old run's late frame is not applied to a new one.
  const blockOfRun = new Map<string, string>()
  const runIdOfBlock = new Map<string, string>()
  // Run frames that came before the POST answered with their run_id, per session.
  const earlyFrames = new Map<string, RunFrame[]>()
  const startingCount = new Map<string, number>()
  const busyTimers = new Map<string, ReturnType<typeof setTimeout>>()
  let seq = 0

  function patch(sessionId: string, changes: Partial<TerminalSession>): void {
    sessions.value = { ...sessions.value, [sessionId]: { ...(sessions.value[sessionId] ?? emptySession()), ...changes } }
  }

  function emit(sessionId: string, data: string, reset: boolean): void {
    listeners.get(sessionId)?.forEach((cb) => cb(data, reset))
  }

  function applyRunFrame(frame: RunFrame): boolean {
    const blockKey = blockOfRun.get(frame.run_id)
    if (blockKey === undefined || runIdOfBlock.get(blockKey) !== frame.run_id) return false
    runs.value = { ...runs.value, [blockKey]: { state: frame.state, exitCode: frame.exit_code, blockKey } }
    return true
  }

  function onFrame(sessionId: string, frame: TerminalFrame): void {
    switch (frame.type) {
      case 'replay':
        patch(sessionId, { connected: true, exited: false, buffer: clip(frame.data) })
        emit(sessionId, frame.data, true)
        break
      case 'output':
        patch(sessionId, { buffer: clip((sessions.value[sessionId]?.buffer ?? '') + frame.data) })
        emit(sessionId, frame.data, false)
        break
      case 'busy':
        patch(sessionId, { busy: frame.busy })
        break
      case 'exit':
        patch(sessionId, { exited: true, busy: false })
        break
      case 'run':
        // A run the POST has not answered for yet: keep the frame for when it does.
        if (!applyRunFrame(frame) && (startingCount.get(sessionId) ?? 0) > 0) {
          earlyFrames.set(sessionId, [...(earlyFrames.get(sessionId) ?? []), frame])
        }
        break
    }
  }

  function connect(sessionId: string): void {
    if (sockets.has(sessionId)) return
    const socket = new TerminalSocket(sessionId)
    sockets.set(sessionId, socket)
    patch(sessionId, { connected: false, exited: false, busy: false })
    socket.onFrame((frame) => {
      if (sockets.get(sessionId) === socket) onFrame(sessionId, frame)
    })
    socket.onClose(() => {
      // A socket already replaced or dropped by `disconnect` says nothing about the current one.
      if (sockets.get(sessionId) !== socket) return
      sockets.delete(sessionId)
      patch(sessionId, { connected: false, busy: false })
    })
  }

  function disconnect(sessionId: string): void {
    const socket = sockets.get(sessionId)
    if (!socket) return
    sockets.delete(sessionId)
    socket.close()
    patch(sessionId, { connected: false, busy: false })
  }

  function onOutput(sessionId: string, cb: OutputListener): () => void {
    let set = listeners.get(sessionId)
    if (!set) {
      set = new Set()
      listeners.set(sessionId, set)
    }
    set.add(cb)
    return () => {
      set.delete(cb)
      if (set.size === 0 && listeners.get(sessionId) === set) listeners.delete(sessionId)
    }
  }

  function sendInput(sessionId: string, data: string): void {
    sockets.get(sessionId)?.sendInput(data)
  }

  function resize(sessionId: string, cols: number, rows: number): void {
    sockets.get(sessionId)?.resize(cols, rows)
  }

  function openPanel(sessionId: string): void {
    seq += 1
    panelRequest.value = { sessionId, seq }
  }

  function setRun(blockKey: string, state: RunState, exitCode: number | null = null): void {
    runs.value = { ...runs.value, [blockKey]: { state, exitCode, blockKey } }
  }

  function dropRun(blockKey: string): void {
    const { [blockKey]: _gone, ...rest } = runs.value
    runs.value = rest
  }

  function forgetRunId(blockKey: string): void {
    const old = runIdOfBlock.get(blockKey)
    if (old !== undefined) blockOfRun.delete(old)
    runIdOfBlock.delete(blockKey)
  }

  async function run(sessionId: string, command: string, blockKey: string): Promise<void> {
    const current = runs.value[blockKey]?.state
    if (current === 'starting' || current === 'running') return
    const timer = busyTimers.get(blockKey)
    if (timer) clearTimeout(timer)
    busyTimers.delete(blockKey)
    forgetRunId(blockKey)

    openPanel(sessionId)
    connect(sessionId)
    setRun(blockKey, 'starting')
    startingCount.set(sessionId, (startingCount.get(sessionId) ?? 0) + 1)
    try {
      const { run_id } = await runInTerminal(sessionId, command)
      blockOfRun.set(run_id, blockKey)
      runIdOfBlock.set(blockKey, run_id)
      const early = earlyFrames.get(sessionId) ?? []
      const rest = early.filter((frame) => frame.run_id !== run_id)
      early.filter((frame) => frame.run_id === run_id).forEach(applyRunFrame)
      if (rest.length > 0) earlyFrames.set(sessionId, rest)
      else earlyFrames.delete(sessionId)
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setRun(blockKey, 'busy')
        busyTimers.set(
          blockKey,
          setTimeout(() => {
            busyTimers.delete(blockKey)
            if (runs.value[blockKey]?.state === 'busy') dropRun(blockKey)
          }, BUSY_RESET_MS),
        )
      } else {
        setRun(blockKey, 'failed')
      }
    } finally {
      const left = (startingCount.get(sessionId) ?? 1) - 1
      if (left > 0) startingCount.set(sessionId, left)
      else {
        startingCount.delete(sessionId)
        earlyFrames.delete(sessionId)
      }
    }
  }

  /** The state of a play button; `idle` when it has no run. */
  function runStateFor(blockKey: string): RunState | 'idle' {
    return runs.value[blockKey]?.state ?? 'idle'
  }

  async function close(sessionId: string): Promise<void> {
    await closeTerminal(sessionId)
  }

  function attach(sessionId: string, text: string): void {
    if (!text.trim()) return
    attachments.value = { ...attachments.value, [sessionId]: [...(attachments.value[sessionId] ?? []), text] }
  }

  function removeAttachment(sessionId: string, index: number): void {
    const list = attachments.value[sessionId]
    if (!list || index < 0 || index >= list.length) return
    const next = list.filter((_, i) => i !== index)
    if (next.length > 0) {
      attachments.value = { ...attachments.value, [sessionId]: next }
    } else {
      const { [sessionId]: _gone, ...rest } = attachments.value
      attachments.value = rest
    }
  }

  function takeAttachments(sessionId: string): string[] {
    const list = attachments.value[sessionId] ?? []
    if (list.length === 0) return []
    const { [sessionId]: _gone, ...rest } = attachments.value
    attachments.value = rest
    return [...list]
  }

  return {
    sessions,
    runs,
    attachments,
    panelRequest,
    connect,
    disconnect,
    onOutput,
    sendInput,
    resize,
    openPanel,
    run,
    runStateFor,
    close,
    attach,
    removeAttachment,
    takeAttachments,
  }
})
