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

const user = (id: string) => ({ type: 'user', id, text: id })
const tool = (id: string, name: string, extra: Record<string, unknown> = {}) => ({
  type: 'tool', id, tool_use_id: `tu-${id}`, name, input: { file_path: `/p/${id}.py` },
  result: { content: 'ok', is_error: false, details: null }, streaming: false, parent_tool_use_id: null, ...extra,
})
const bg = (id: string, status: string | null, extra: Record<string, unknown> = {}) => tool(id, 'Bash', {
  input: { command: `sleep ${id}`, description: `cmd ${id}`, run_in_background: true },
  background: status ? { task_id: `b-${id}`, status, summary: null } : null, ...extra,
})
const text = (id: string) => ({ type: 'text', id, text: `texto ${id}`, streaming: false, parent_tool_use_id: null })
const agent = (id: string, status: string) => tool(id, 'Agent', {
  input: { subagent_type: 'reviewer', description: `desc ${id}` }, result: null,
  subagent: { task_id: 't', subagent_type: 'reviewer', description: `desc ${id}`, status, last_activity: null, usage: null, summary: null },
})

async function mountWith(snapshot: Record<string, unknown>, fetches: Record<string, () => Response> = {}) {
  vi.stubGlobal('fetch', routeFetch({ 'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ seq: 1, ...snapshot })), ...fetches }))
  const router = createAppRouter(createMemoryHistory())
  await router.push('/sessions/s1')
  const w = mount(ConversationThread, { props: { id: 's1', visible: true }, global: { plugins: [pinia, router] }, attachTo: document.body })
  await flushPromises()
  return w
}
const ends = (w: Awaited<ReturnType<typeof mountWith>>) => w.findAll('[data-test="turn-end"]')

describe('rodapé do turno', () => {
  it('é uma linha discreta, sem caixa, com ✓, "Concluído" e o resumo', async () => {
    const w = await mountWith({ state: 'idle', items: [user('u1'), tool('e1', 'Edit'), tool('r1', 'Read')] })
    const end = ends(w)[0]!
    expect(end.text().replace(/\s+/g, ' ')).toBe('Concluído · 2 ações · 1 arquivo alterado')
    expect(end.find('svg').exists()).toBe(true)
    expect(end.classes()).not.toEqual(expect.arrayContaining(['bg-panel']))
    expect(end.classes().some((c) => c.startsWith('border') || c === 'rounded-lg')).toBe(false)
    expect(end.text()).not.toContain('Turno concluído')
  })

  it('junta duração e custo, na ordem', async () => {
    const w = await mountWith({ state: 'idle', items: [user('u1'), tool('r1', 'Read')] })
    fake.session.get('s1')!(makeEvent('turn.result', { subtype: 'success', is_error: false, duration_ms: 48000, total_cost_usd: 0.12 }, 2))
    await flushPromises()
    expect(ends(w)[0]!.text().replace(/\s+/g, ' ')).toBe('Concluído · 1 ação · 48 s · US$ 0,12')
  })

  it('turnos antigos ficam todos em cinza; só o último tem ✓ e palavra em verde', async () => {
    const w = await mountWith({ state: 'idle', items: [user('u1'), tool('r1', 'Read'), user('u2'), tool('r2', 'Read')] })
    const [old, last] = ends(w)
    expect(old!.find('.text-primary, .text-primary-soft').exists()).toBe(false)
    expect(old!.find('.text-fg-subtle').exists()).toBe(true)
    expect(last!.find('svg').classes()).toContain('text-primary')
    expect(last!.find('[data-test="turn-end-label"]').classes()).toContain('text-primary-soft')
    expect(last!.find('[data-test="turn-end-summary"]').classes()).toContain('text-fg-subtle')
  })

  it('"terminou com erro" continua em vermelho', async () => {
    const w = await mountWith({ state: 'idle', items: [user('u1'), tool('r1', 'Read')] })
    fake.session.get('s1')!(makeEvent('turn.result', { subtype: 'error', is_error: true, duration_ms: 1000, total_cost_usd: null }, 2))
    await flushPromises()
    const error = ends(w)[0]!.find('[data-test="turn-end-error"]')
    expect(error.text()).toBe('terminou com erro')
    expect(error.classes()).toContain('text-diff-del-fg')
  })

  it('com o turno em andamento o rodapé nem aparece, mesmo com comando em background rodando', async () => {
    const w = await mountWith({ state: 'running', items: [user('u1'), bg('b', 'running')] })
    expect(ends(w)).toHaveLength(0)
  })
})

describe('rodapé aguardando background', () => {
  const waiting = (w: Awaited<ReturnType<typeof mountWith>>) => w.find('[data-test="turn-waiting"]')

  it('turno terminado com comando rodando: bolinha pulsante e "Aguardando 1 comando em background"', async () => {
    const w = await mountWith({ state: 'idle', items: [user('u1'), bg('b', 'running')] })
    const end = ends(w)[0]!
    expect(end.text()).toContain('Aguardando 1 comando em background')
    expect(end.text()).not.toContain('Concluído')
    const dot = end.find('[data-test="turn-waiting-dot"]')
    expect(dot.classes()).toEqual(expect.arrayContaining(['bg-secondary', 'animate-pulse', 'motion-reduce:animate-none']))
    expect(dot.classes()).not.toContain('bg-primary')
    expect(dot.attributes('aria-hidden')).toBe('true')
    // Espera é aviso discreto: o texto fica neutro e nada nele é verde.
    expect(end.find('[data-test="turn-waiting"]').classes()).toContain('text-fg-muted')
    expect(end.find('.text-primary, .text-primary-soft, .bg-primary').exists()).toBe(false)
    expect(end.find('svg').exists()).toBe(false)
  })

  it('conta comandos e subagentes juntos', async () => {
    const w = await mountWith({ state: 'idle', items: [user('u1'), agent('a', 'running'), bg('b', 'running'), bg('c', 'completed')] })
    expect(ends(w)[0]!.text()).toContain('Aguardando 2 tarefas em background')
  })

  it('só o rodapé do último turno muda; os anteriores continuam "Concluído"', async () => {
    const w = await mountWith({ state: 'idle', items: [user('u1'), tool('r1', 'Read'), user('u2'), bg('b', 'running')] })
    const [first, last] = ends(w)
    expect(first!.text()).toContain('Concluído')
    expect(last!.text()).toContain('Aguardando 1 comando em background')
  })

  it('comando de um turno anterior ainda rodando também faz o último turno aguardar', async () => {
    const w = await mountWith({ state: 'idle', items: [user('u1'), bg('b', 'running'), user('u2'), tool('r2', 'Read')] })
    const [first, last] = ends(w)
    expect(first!.text()).toContain('Concluído')
    expect(last!.text()).toContain('Aguardando 1 comando em background')
  })

  it('comando sem status ao vivo (histórico) não conta: o turno aparece concluído', async () => {
    const w = await mountWith({ state: 'idle', items: [user('u1'), bg('b', null)] })
    expect(ends(w)[0]!.text()).toContain('Concluído')
    expect(waiting(w).exists()).toBe(false)
  })

  it('comando já terminado não faz o turno aguardar', async () => {
    const w = await mountWith({ state: 'idle', items: [user('u1'), bg('b', 'completed')] })
    expect(ends(w)[0]!.text()).toContain('Concluído')
  })

  it('volta a "Concluído" quando o comando termina', async () => {
    const w = await mountWith({ state: 'idle', items: [user('u1'), bg('b', 'running')] })
    expect(ends(w)[0]!.text()).toContain('Aguardando')
    fake.session.get('s1')!(makeEvent('item.upsert', bg('b', 'completed'), 2))
    await flushPromises()
    expect(ends(w)[0]!.text()).toContain('Concluído')
    expect(ends(w)[0]!.text()).not.toContain('Aguardando')
  })

  it('é um botão; o clique leva ao cartão do primeiro que está rodando', async () => {
    const w = await mountWith({ state: 'idle', items: [user('u1'), bg('done', 'completed'), text('t1'), bg('first', 'running'), text('t2'), bg('second', 'running')] })
    const button = waiting(w)
    expect(button.element.tagName).toBe('BUTTON')
    expect(button.attributes('type')).toBe('button')
    // The block is open while the card sits in a closed row: the click opens the row.
    expect(w.find('[data-subagent-id="first"]').exists()).toBe(false)
    const scrollIntoView = vi.fn()
    Element.prototype.scrollIntoView = scrollIntoView
    await button.trigger('click')
    await flushPromises()
    const card = w.find('[data-subagent-id="first"]')
    expect(card.exists()).toBe(true)
    expect(scrollIntoView).toHaveBeenCalled()
    expect(scrollIntoView.mock.contexts[0]).toBe(card.element)
    expect(card.attributes('data-highlighted')).toBe('true')
  })

  it('o clique abre o bloco recolhido que guarda o comando e destaca o cartão', async () => {
    const w = await mountWith({ state: 'idle', items: [user('u1'), bg('b', 'running'), tool('r1', 'Read')] })
    expect(w.find('[data-test="work-block-toggle"]').attributes('aria-expanded')).toBe('false')
    expect(w.find('[data-subagent-id="b"]').exists()).toBe(false)
    await waiting(w).trigger('click')
    await flushPromises()
    const card = w.find('[data-subagent-id="b"]')
    expect(w.find('[data-test="work-block-toggle"]').attributes('aria-expanded')).toBe('true')
    expect(card.exists()).toBe(true)
    expect(card.attributes('data-highlighted')).toBe('true')
  })
})

describe('faixa com comandos em background', () => {
  it('lista o comando rodando com a sessão ociosa e "Parar comando" chama a rota da sessão', async () => {
    const stopped = vi.fn(() => jsonResponse({}, 202))
    const w = await mountWith(
      { state: 'idle', items: [user('u1'), bg('b', 'running'), user('u2')] },
      { 'POST /api/sessions/s1/subagents/stop': stopped },
    )
    const strip = w.find('[data-test="subagent-strip"]')
    expect(strip.text()).toContain('Comando')
    expect(strip.text()).toContain('cmd b')
    const stop = w.find('[data-test="subagent-stop"]')
    expect(stop.text()).toBe('Parar comando')
    await stop.trigger('click')
    await flushPromises()
    expect(stopped).toHaveBeenCalled()
  })

  it('clicar na linha leva ao cartão do comando', async () => {
    const w = await mountWith({ state: 'idle', items: [user('u1'), bg('b', 'running')] })
    expect(w.find('[data-subagent-id="b"]').exists()).toBe(false)
    const scrollIntoView = vi.fn()
    Element.prototype.scrollIntoView = scrollIntoView
    await w.find('[data-test="subagent-row"]').trigger('click')
    await flushPromises()
    const card = w.find('[data-subagent-id="b"]')
    expect(scrollIntoView).toHaveBeenCalled()
    expect(card.attributes('data-highlighted')).toBe('true')
  })

  it('não aparece para comando sem status ao vivo', async () => {
    const w = await mountWith({ state: 'idle', items: [user('u1'), bg('b', null)] })
    expect(w.find('[data-test="subagent-strip"]').exists()).toBe(false)
  })
})
