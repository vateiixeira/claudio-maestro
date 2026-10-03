import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../../../router'
import { jsonResponse, makeEvent, makeProject, makeSnapshot, routeFetch } from '../../../test/factories'
import { useProjectsStore } from '../../../stores/projects'
import { useGitStore } from '../../../stores/git'
import type { ConversationItem } from '../../../types/conversation'

const fake = vi.hoisted(() => ({ session: new Map<string, (e: unknown) => void>() }))
vi.mock('../../../api/socket', () => ({
  useEventSocket: () => ({
    onSession: (id: string, h: (e: unknown) => void) => { fake.session.set(id, h); return () => fake.session.delete(id) },
    onReconnect: () => () => {},
    onOpen: () => () => {},
  }),
}))

import ConversationThread from '../ConversationThread.vue'

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

const th = (id: string, text: string, streaming = false, parent: string | null = null) => ({ type: 'thinking', id, text, streaming, parent_tool_use_id: parent })
const user = (id: string) => ({ type: 'user', id, text: id })
const agent = {
  type: 'tool', id: 'a', tool_use_id: 'tu-a', name: 'Agent', input: { subagent_type: 'reviewer', description: 'Revisar' },
  result: null, streaming: false, parent_tool_use_id: null,
  subagent: { task_id: 't', subagent_type: 'reviewer', description: 'Revisar', status: 'running', last_activity: null, usage: null, summary: null },
}

async function mountWith(items: Record<string, unknown>[]) {
  vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ seq: 1, state: 'running', items: items as unknown as ConversationItem[] })) }))
  const router = createAppRouter(createMemoryHistory())
  await router.push('/sessions/s1')
  const w = mount(ConversationThread, { props: { id: 's1', visible: true }, global: { plugins: [pinia, router] }, attachTo: document.body })
  await flushPromises()
  return w
}

describe('pensamento na conversa', () => {
  it('pensamentos seguidos viram um bloco só e o vazio terminado não aparece', async () => {
    const w = await mountWith([user('u1'), th('t1', 'primeiro'), th('t2', ''), th('t3', 'segundo')])
    expect(w.findAll('[data-kind="thinking"]')).toHaveLength(1)
    expect(w.findAll('[data-test="thinking-text"]')).toHaveLength(0)
    await w.find('[data-kind="thinking"] + * button[aria-expanded]').trigger('click')
    expect(w.find('[data-test="thinking-text"]').text()).toBe('primeiro\n\nsegundo')
  })

  it('dentro de um subagente vale a mesma regra', async () => {
    const w = await mountWith([user('u1'), agent, th('c1', 'um', false, 'tu-a'), th('c2', '  ', false, 'tu-a'), th('c3', 'dois', false, 'tu-a')])
    const kids = w.find('[data-test="subagent-children"]')
    expect(kids.findAll('button[aria-expanded]')).toHaveLength(1)
    await kids.find('button[aria-expanded]').trigger('click')
    expect(kids.find('[data-test="thinking-text"]').text()).toBe('um\n\ndois')
  })

  it('filho com pensamento vazio terminado não deixa rótulo solto', async () => {
    const w = await mountWith([user('u1'), agent, th('c1', '', false, 'tu-a')])
    expect(w.find('[data-test="subagent-children"] [data-kind="thinking"]').exists()).toBe(false)
    expect(w.find('[data-test="subagent-children"] button[aria-expanded]').exists()).toBe(false)
  })

  it('pensamento que chega depois de outro terminado continua o mesmo bloco, com o tempo somado', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] })
    try {
      const w = await mountWith([user('u1'), th('t1', 'um', true)])
      const emit = (e: unknown) => fake.session.get('s1')!(e)
      const label = () => w.find('[data-kind="thinking"] + *').text()
      await vi.advanceTimersByTimeAsync(2000)
      expect(label()).toContain('Pensando…')
      expect(label()).toContain('· 2 s')
      const el = w.find('[data-kind="thinking"] + *').element
      emit(makeEvent('item.upsert', th('t1', 'um', false), 2))
      await flushPromises()
      expect(label()).toContain('Raciocínio')
      expect(label()).toContain('· 2 s')
      emit(makeEvent('item.upsert', th('t2', 'dois', true), 3))
      await flushPromises()
      expect(w.findAll('[data-kind="thinking"]')).toHaveLength(1)
      expect(label()).toContain('Pensando…')
      expect(label()).toContain('· 2 s')
      await vi.advanceTimersByTimeAsync(3000)
      expect(label()).toContain('· 5 s')
      emit(makeEvent('item.upsert', th('t2', 'dois', false), 4))
      await flushPromises()
      expect(label()).toContain('Raciocínio')
      expect(label()).toContain('· 5 s')
      expect(w.find('[data-kind="thinking"] + *').element).toBe(el)
    } finally {
      vi.useRealTimers()
    }
  })
})
