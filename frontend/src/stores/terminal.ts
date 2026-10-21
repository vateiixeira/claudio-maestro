import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ApiError, closeTerminal, runInTerminal } from '../api/http'
import { TerminalSocket, type ReplayRun, type TerminalFrame } from '../api/terminalSocket'

/** What the store keeps of one session's terminal. */
export interface TerminalSession {
  connected: boolean
  busy: boolean
  exited: boolean
  /** The socket closed (refused, dropped or ended by the server); `closeCode` says how. */
  closed: boolean
  closeCode: number | null
  buffer: string
}

export type RunState = 'starting' | 'running' | 'sent' | 'interrupted' | 'failed' | 'busy'

/** One click on a play button, followed until the output is sent to Claude. */
export interface TerminalRunInfo {
  state: RunState
  exitCode: number | null
  blockKey: string
  /** Why a run failed, when the server said (for example the session's folder is gone). */
  message?: string
}

type RunFrame = Extract<TerminalFrame, { type: 'run' }>

/** Called with new output. `reset` is true when `data` is a replay that replaces everything shown. */
export type OutputListener = (data: string, reset: boolean) => void

/** The server's reason when the session's folder is gone; the run says it instead of "busy". */
export const FOLDER_GONE_DETAIL = 'A pasta da sessão não existe mais.'
/** The close code of a socket that only attaches when the session has no terminal. */
export const NO_TERMINAL_CODE = 4410

/** The most the buffer keeps, the same limit the server uses for the replay. */
export const BUFFER_LIMIT = 262_144
/** How long a refused run (terminal busy) shows "busy" before the play button is idle again. */
export const BUSY_RESET_MS = 2500

function emptySession(): TerminalSession {
  return { connected: false, busy: false, exited: false, closed: false, closeCode: null, buffer: '' }
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
  // The last state the server reported for each run_id (replay and run frames), per session, so a POST
  // that answers after the server already told the outcome still ends up with it.
  const knownRuns = new Map<string, Map<string, ReplayRun>>()
  // Which session each block's run belongs to.
  const sessionOfBlock = new Map<string, string>()
  const socketModes = new Map<string, boolean>()
  // A gesture (tab, header button, play) asked for the terminal: the pane that mounts for it opens the shell.
  const openRequests = new Set<string>()
  const lastSize = new Map<string, { cols: number; rows: number }>()
  const startingCount = new Map<string, number>()
  const busyTimers = new Map<string, ReturnType<typeof setTimeout>>()
  let seq = 0

  function patch(sessionId: string, changes: Partial<TerminalSession>): void {
    sessions.value = { ...sessions.value, [sessionId]: { ...(sessions.value[sessionId] ?? emptySession()), ...changes } }
  }

  function emit(sessionId: string, data: string, reset: boolean): void {
    listeners.get(sessionId)?.forEach((cb) => cb(data, reset))
  }

  const KNOWN_RUNS_LIMIT = 50

  function remember(sessionId: string, frame: ReplayRun): void {
    const known = knownRuns.get(sessionId) ?? new Map<string, ReplayRun>()
    known.delete(frame.run_id)
    known.set(frame.run_id, frame)
    if (known.size > KNOWN_RUNS_LIMIT) known.delete(known.keys().next().value as string)
    knownRuns.set(sessionId, known)
  }

  /**
   * Runs of this session that the server can no longer be running. With `reported` (a replay's runs) the
   * server's word wins for every run it lists, even one marked interrupted here by a missed frame; a
   * running run it does not list is over.
   */
  function interruptRunning(sessionId: string, reported?: Map<string, ReplayRun>): void {
    const next = { ...runs.value }
    let changed = false
    for (const [blockKey, info] of Object.entries(runs.value)) {
      if (sessionOfBlock.get(blockKey) !== sessionId) continue
      const runId = runIdOfBlock.get(blockKey)
      if (runId === undefined) continue
      const entry = reported?.get(runId)
      if (entry) {
        if (info.state === entry.state && info.exitCode === entry.exit_code) continue
        next[blockKey] = { state: entry.state, exitCode: entry.exit_code, blockKey }
      } else if (info.state === 'running') {
        next[blockKey] = { state: 'interrupted', exitCode: null, blockKey }
      } else {
        continue
      }
      changed = true
    }
    if (changed) runs.value = next
  }

  function applyRunFrame(frame: RunFrame): boolean {
    const blockKey = blockOfRun.get(frame.run_id)
    if (blockKey === undefined || runIdOfBlock.get(blockKey) !== frame.run_id) return false
    runs.value = { ...runs.value, [blockKey]: { state: frame.state, exitCode: frame.exit_code, blockKey } }
    return true
  }

  function onFrame(sessionId: string, frame: TerminalFrame): void {
    switch (frame.type) {
      case 'replay': {
        // The replay tells which runs the terminal still has: a run we think is running and it does not know is over.
        if (frame.runs) {
          frame.runs.forEach((entry) => remember(sessionId, entry))
          interruptRunning(sessionId, new Map(frame.runs.map((entry) => [entry.run_id, entry])))
        }
        patch(sessionId, { connected: true, exited: false, buffer: clip(frame.data) })
        emit(sessionId, frame.data, true)
        break
      }
      case 'output':
        patch(sessionId, { buffer: clip((sessions.value[sessionId]?.buffer ?? '') + frame.data) })
        emit(sessionId, frame.data, false)
        break
      case 'busy':
        patch(sessionId, { busy: frame.busy })
        break
      case 'exit':
        patch(sessionId, { exited: true, busy: false })
        interruptRunning(sessionId)
        break
      case 'run':
        remember(sessionId, frame)
        applyRunFrame(frame)
        break
    }
  }

  /**
   * Connects to the session's terminal. With `open` the server starts the shell if there is none (a user
   * gesture); without it the socket only attaches and is closed with 4410 when there is no terminal.
   */
  function connect(sessionId: string, open = false): void {
    const existing = sockets.get(sessionId)
    if (existing) {
      // A socket that only attaches and has not found a terminal yet cannot start one: replace it.
      if (!open || socketModes.get(sessionId) || sessions.value[sessionId]?.connected) return
      sockets.delete(sessionId)
      existing.close()
    }
    const socket = new TerminalSocket(sessionId, open)
    sockets.set(sessionId, socket)
    socketModes.set(sessionId, open)
    const size = lastSize.get(sessionId)
    if (size) socket.resize(size.cols, size.rows)
    patch(sessionId, { connected: false, exited: false, busy: false, closed: false, closeCode: null })
    socket.onFrame((frame) => {
      if (sockets.get(sessionId) === socket) onFrame(sessionId, frame)
    })
    socket.onClose((code) => {
      // A socket already replaced or dropped by `disconnect` says nothing about the current one.
      if (sockets.get(sessionId) !== socket) return
      sockets.delete(sessionId)
      patch(sessionId, { connected: false, busy: false, closed: true, closeCode: code })
      // No terminal there: whatever run was waiting on it is over.
      if (code === NO_TERMINAL_CODE) interruptRunning(sessionId)
    })
  }

  function disconnect(sessionId: string): void {
    openRequests.delete(sessionId)
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
    lastSize.set(sessionId, { cols, rows })
    sockets.get(sessionId)?.resize(cols, rows)
  }

  /** A gesture asked for this session's terminal: the next pane to mount connects in "open" mode. */
  function requestOpen(sessionId: string): void {
    openRequests.add(sessionId)
  }

  /** True once if a gesture asked to open; a pane mounted by a remembered tab only attaches. */
  function takeOpenRequest(sessionId: string): boolean {
    return openRequests.delete(sessionId)
  }

  function openPanel(sessionId: string): void {
    requestOpen(sessionId)
    seq += 1
    panelRequest.value = { sessionId, seq }
  }

  function setRun(blockKey: string, state: RunState, exitCode: number | null = null, message?: string): void {
    runs.value = { ...runs.value, [blockKey]: { state, exitCode, blockKey, ...(message ? { message } : {}) } }
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
    connect(sessionId, true)
    sessionOfBlock.set(blockKey, sessionId)
    setRun(blockKey, 'starting')
    startingCount.set(sessionId, (startingCount.get(sessionId) ?? 0) + 1)
    try {
      const { run_id } = await runInTerminal(sessionId, command)
      blockOfRun.set(run_id, blockKey)
      runIdOfBlock.set(blockKey, run_id)
      // The server may have told the outcome (run frames, or a replay) before this answer came.
      const known = knownRuns.get(sessionId)?.get(run_id)
      if (known) applyRunFrame({ type: 'run', ...known })
      // The server answers only after it published `running`, so a run still `starting` here missed that
      // frame (the socket was down): it is running now, and replay, exit or a 4410 will settle it.
      else if (runs.value[blockKey]?.state === 'starting' && runIdOfBlock.get(blockKey) === run_id) setRun(blockKey, 'running')
    } catch (error) {
      const folderGone = error instanceof ApiError && error.status === 409 && error.detail === FOLDER_GONE_DETAIL
      if (folderGone) {
        setRun(blockKey, 'failed', null, FOLDER_GONE_DETAIL)
      } else if (error instanceof ApiError && error.status === 409) {
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
      else startingCount.delete(sessionId)
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
    requestOpen,
    takeOpenRequest,
    run,
    runStateFor,
    close,
    attach,
    removeAttachment,
    takeAttachments,
  }
})
