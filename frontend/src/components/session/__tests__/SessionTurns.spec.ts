import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../../router'
import { jsonResponse, makeEvent, makeProject, makeSnapshot, routeFetch } from '../../../test/factories'
import { useProjectsStore } from '../../../stores/projects'
import { useGitStore } from '../../../stores/git'

const fake = vi.hoisted(() => ({ session: new Map<string, (e: unknown) => void>() }))
vi.mock('../../../api/socket', () => ({
  useEventSocket: () => ({
    onSession: (id: string, h: (e: unknown) => void) => { fake.session.set(id, h); return () => fake.session.delete(id) },
    onReconnect: () => () => {},
    onOpen: () => () => {},
  }),
}))

import SessionColumn from '../SessionColumn.vue'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  fake.session.clear()
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1 })]
  projects.loaded = true
  useGitStore(pinia).set(1, [])
})
afterEach(() => vi.unstubAllGlobals())

const user = (id: string, t = id) => ({ type: 'user', id, text: t })
const text = (id: string) => ({ type: 'text', id, text: `texto ${id}`, streaming: false, parent_tool_use_id: null })
const tool = (id: string, name: string, extra: Record<string, unknown> = {}) => ({
  type: 'tool', id, tool_use_id: `tu-${id}`, name, input: { file_path: `/p/${id}.py` },
  result: { content: 'ok', is_error: false, details: null }, streaming: false, parent_tool_use_id: null, ...extra,
})

async function mountWith(snapshot: Record<string, unknown>) {
  vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ seq: 1, ...snapshot })) }))
  const router = createAppRouter(createMemoryHistory())
  await router.push('/sessions/s1')
  const w = mount(SessionColumn, { props: { id: 's1', visible: true }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return w
}

describe('chat em turnos', () => {
  it('rótulo VOCÊ, separador a partir do segundo turno e resumo dos turnos terminados', async () => {
    const w = await mountWith({
      state: 'running',
      items: [user('u1', 'primeiro'), tool('e1', 'Edit'), tool('r1', 'Read'), text('a'), user('u2', 'segundo'), text('b')],
    })
    const turns = w.findAll('[data-test="turn"]')
    expect(turns).toHaveLength(2)
    expect(w.findAll('[data-test="user-message-card"]')[0]!.text()).toContain('Você')
    const seps = w.findAll('[data-test="turn-separator"]')
    expect(seps).toHaveLength(1)
    expect(seps[0]!.text()).toBe('Turno 2')
    const ends = w.findAll('[data-test="turn-end"]')
    expect(ends).toHaveLength(1)
    expect(ends[0]!.text()).toContain('Turno concluído')
    expect(ends[0]!.text()).toContain('2 ações · 1 arquivo alterado')
  })

  it('último turno termina quando a sessão para e junta o resultado', async () => {
    const w = await mountWith({ state: 'idle', items: [user('u1'), tool('r1', 'Read')] })
    fake.session.get('s1')!(makeEvent('turn.result', { subtype: 'success', is_error: false, duration_ms: 1500, total_cost_usd: null }, 2))
    await flushPromises()
    const end = w.find('[data-test="turn-end"]')
    expect(end.text()).toContain('1 ação')
    expect(end.text()).not.toContain('arquivo')
    expect(end.text()).toContain('1,5 s')
    expect(w.find('[data-test="turn-footer"]').exists()).toBe(false)
  })

  it('nós do trilho: rodando e com erro', async () => {
    const w = await mountWith({
      state: 'running',
      items: [user('u1'), tool('b1', 'Bash', { result: { content: 'x', is_error: true, details: null } }), tool('b2', 'Bash', { result: null })],
    })
    const nodes = w.findAll('[data-test="rail-node"]')
    expect(nodes.map((n) => n.attributes('data-kind'))).toEqual(['error', 'running'])
    expect(nodes[0]!.attributes('aria-hidden')).toBe('true')
  })
})
