import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useClaudeCliStore } from '../claudeCli'

const INFO = {
  in_use: { source: 'system', version: '2.1.292' },
  system: { path: '/opt/bin/claude', version: '2.1.292' },
  bundled: { version: '2.1.284' },
  forced_bundled: false,
  can_update: true,
  job: null,
}
const RESULT = {
  ok: true, before: '2.1.292', after: '2.1.295', in_use: { source: 'system', version: '2.1.295' },
  models_refreshed: true, output: 'ok', message: 'Claude atualizado de 2.1.292 para 2.1.295. A lista de modelos foi renovada.',
}

function respond(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
}

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

describe('claudeCli store', () => {
  it('loads the info', async () => {
    vi.stubGlobal('fetch', vi.fn(() => respond(200, INFO)))
    const store = useClaudeCliStore()
    await store.load()
    expect(store.info?.in_use.version).toBe('2.1.292')
    expect(store.busy).toBe(false)
  })

  it('keeps the last info when loading fails', async () => {
    const fetch = vi.fn().mockReturnValueOnce(respond(200, INFO)).mockReturnValueOnce(respond(500, {}))
    vi.stubGlobal('fetch', fetch)
    const store = useClaudeCliStore()
    await store.load()
    await store.load()
    expect(store.info?.in_use.version).toBe('2.1.292')
  })

  it('is busy while the backend reports a running job', async () => {
    vi.stubGlobal('fetch', vi.fn(() => respond(200, { ...INFO, job: { state: 'running' } })))
    const store = useClaudeCliStore()
    await store.load()
    expect(store.busy).toBe(true)
  })

  it('update shows the message, reloads, and is busy meanwhile', async () => {
    let release!: () => void
    const fetch = vi.fn((_url: string, init?: RequestInit) => {
      if (init?.method === 'POST') return new Promise<Response>((r) => { release = () => r(new Response(JSON.stringify(RESULT), { status: 200 })) })
      return respond(200, { ...INFO, in_use: { source: 'system', version: '2.1.295' } })
    })
    vi.stubGlobal('fetch', fetch)
    const store = useClaudeCliStore()
    const done = store.update()
    expect(store.busy).toBe(true)
    release()
    await done
    expect(store.busy).toBe(false)
    expect(store.result).toEqual({ ok: true, message: RESULT.message })
    expect(store.info?.in_use.version).toBe('2.1.295')
  })

  it('update error shows the backend detail', async () => {
    vi.stubGlobal('fetch', vi.fn(() => respond(409, { detail: 'Já há uma atualização do Claude em andamento.' })))
    const store = useClaudeCliStore()
    await store.update()
    expect(store.result).toEqual({ ok: false, message: 'Já há uma atualização do Claude em andamento.' })
  })

  it('a second update while one runs does nothing', async () => {
    const fetch = vi.fn(() => new Promise<Response>(() => {}))
    vi.stubGlobal('fetch', fetch)
    const store = useClaudeCliStore()
    void store.update()
    void store.update()
    expect(fetch).toHaveBeenCalledTimes(1)
  })
})
