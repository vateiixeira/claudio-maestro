import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import ConversationHeader from '../ConversationHeader.vue'
import { createAppRouter } from '../../../router'
import { conversationFromSnapshot, useConversationStore } from '../../../stores/conversation'
import { useGitStore } from '../../../stores/git'
import { useProjectsStore } from '../../../stores/projects'
import { useSessionsStore } from '../../../stores/sessions'
import { jsonResponse, makeProject, makeSession, makeSnapshot, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
let suggestCalls = 0
let patches: unknown[]
let suggestAnswers: (() => Response | Promise<Response>)[]
let patchAnswer: () => Response

const router = createAppRouter(createMemoryHistory())
const SUGGESTIONS = ['Sugerir títulos de sessão', 'Botão de sugestão no cabeçalho', 'Sugerir título']

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1 })]
  projects.loaded = true
  useGitStore(pinia).set(1, [])
  suggestCalls = 0
  patches = []
  suggestAnswers = []
  patchAnswer = () => jsonResponse(makeSession({ session_id: 's1', title: 'Escolhido' }))
  vi.stubGlobal('fetch', routeFetch({
    'POST /api/sessions/s1/title-suggestions': () => {
      suggestCalls++
      return (suggestAnswers.shift() ?? (() => jsonResponse({ suggestions: SUGGESTIONS })))()
    },
    'PATCH /api/sessions/s1': (init) => {
      patches.push(JSON.parse(init?.body as string))
      return patchAnswer()
    },
  }))
})
afterEach(() => vi.unstubAllGlobals())

function mountHeader(withMessages: boolean | null = true): VueWrapper {
  useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', title: 'Nova sessão' })])
  if (withMessages !== null) {
    useConversationStore(pinia).bySession['s1'] = conversationFromSnapshot({
      ...makeSnapshot({ seq: 1 }),
      items: withMessages ? [{ type: 'user', id: 'u1', text: 'Oi' }] : [],
    } as never)
  }
  return mount(ConversationHeader, { props: { id: 's1' }, global: { plugins: [pinia, router] }, attachTo: document.body })
}

const button = (w: VueWrapper) => w.get<HTMLButtonElement>('[data-test="suggest-title"]')
const panel = (w: VueWrapper) => w.find('[data-test="title-suggest-panel"]')

async function open(w: VueWrapper) {
  await button(w).trigger('click')
  await flushPromises()
}

describe('botão Sugerir título', () => {
  it('fica logo antes do título, depois da trilha, com nome acessível e dica', () => {
    const w = mountHeader()
    const b = button(w)
    expect(b.attributes('title')).toBe('Sugerir título')
    expect(b.attributes('aria-label')).toBe('Sugerir título')
    expect(b.get('svg').attributes('aria-hidden')).toBe('true')
    const order = w.get('[data-test="header-title"]').html()
    expect(order.indexOf('breadcrumb')).toBeLessThan(order.indexOf('suggest-title'))
    expect(order.indexOf('suggest-title')).toBeLessThan(order.indexOf('conversation-title'))
  })

  it('clicar no título continua abrindo a edição manual', async () => {
    const w = mountHeader()
    await w.get('[data-test="conversation-title"]').trigger('click')
    expect(w.find('[data-test="title-input"]').exists()).toBe(true)
    expect(w.find('[data-test="suggest-title"]').exists()).toBe(false)
  })

  it('fica desabilitado numa conversa carregada sem mensagens', () => {
    expect(button(mountHeader(false)).element.disabled).toBe(true)
  })

  it('fica habilitado com mensagens e enquanto a conversa não carregou', () => {
    expect(button(mountHeader(true)).element.disabled).toBe(false)
    expect(button(mountHeader(null)).element.disabled).toBe(false)
  })
})

describe('painel de sugestões', () => {
  it('abre com "Gerando sugestões…" enquanto espera', async () => {
    let release: (r: Response) => void = () => {}
    const pending = new Promise<Response>((resolve) => { release = resolve })
    suggestAnswers = [() => pending]
    const w = mountHeader()
    // A resposta ainda não chegou: o painel já está aberto e avisa.
    await button(w).trigger('click')
    expect(panel(w).exists()).toBe(true)
    const status = panel(w).get('[role="status"]')
    expect(status.text()).toBe('Gerando sugestões…')
    expect(button(w).attributes('aria-expanded')).toBe('true')
    release(jsonResponse({ suggestions: SUGGESTIONS }))
  })

  it('mostra as três sugestões, uma por botão', async () => {
    const w = mountHeader()
    await open(w)
    const items = w.findAll('[data-test="title-suggestion"]')
    expect(items.map((i) => i.text())).toEqual(SUGGESTIONS)
    expect(panel(w).find('[role="status"]').exists()).toBe(false)
    expect(suggestCalls).toBe(1)
  })

  it('clicar numa sugestão renomeia, troca o título e fecha o painel', async () => {
    const w = mountHeader()
    await open(w)
    await w.findAll('[data-test="title-suggestion"]')[1]!.trigger('click')
    await flushPromises()
    expect(patches).toEqual([{ title: SUGGESTIONS[1] }])
    expect(w.get('[data-test="conversation-title"]').text()).toBe(SUGGESTIONS[1])
    expect(useSessionsStore(pinia).find('s1')?.title).toBe('Escolhido')
    expect(panel(w).exists()).toBe(false)
  })

  it('"Gerar outras" pede de novo e troca a lista', async () => {
    suggestAnswers = [
      () => jsonResponse({ suggestions: ['Um', 'Dois', 'Três'] }),
      () => jsonResponse({ suggestions: ['Quatro', 'Cinco', 'Seis'] }),
    ]
    const w = mountHeader()
    await open(w)
    await w.get('[data-test="suggest-again"]').trigger('click')
    await flushPromises()
    expect(suggestCalls).toBe(2)
    expect(w.findAll('[data-test="title-suggestion"]').map((i) => i.text())).toEqual(['Quatro', 'Cinco', 'Seis'])
  })

  it('mostra o erro do servidor no painel e deixa pedir de novo', async () => {
    suggestAnswers = [() => jsonResponse({ detail: 'O login expirou.' }, 502)]
    const w = mountHeader()
    await open(w)
    expect(panel(w).get('[role="alert"]').text()).toBe('O login expirou.')
    expect(w.findAll('[data-test="title-suggestion"]')).toHaveLength(0)
    expect(patches).toEqual([])
    await w.get('[data-test="suggest-again"]').trigger('click')
    await flushPromises()
    expect(w.findAll('[data-test="title-suggestion"]')).toHaveLength(3)
    expect(panel(w).find('[role="alert"]').exists()).toBe(false)
  })

  it('erro ao renomear fica no painel e o título não muda', async () => {
    patchAnswer = () => jsonResponse({ detail: 'Não foi possível salvar.' }, 400)
    const w = mountHeader()
    await open(w)
    await w.findAll('[data-test="title-suggestion"]')[0]!.trigger('click')
    await flushPromises()
    expect(panel(w).exists()).toBe(true)
    expect(panel(w).get('[role="alert"]').text()).toBe('Não foi possível salvar.')
    expect(w.findAll('[data-test="title-suggestion"]')).toHaveLength(3)
    expect(w.get('[data-test="conversation-title"]').text()).toBe('Nova sessão')
  })

  it('Esc fecha sem renomear, devolve o foco ao botão e não dispara outra coisa', async () => {
    const w = mountHeader()
    await open(w)
    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    document.dispatchEvent(event)
    await w.vm.$nextTick()
    expect(event.defaultPrevented).toBe(true)
    expect(panel(w).exists()).toBe(false)
    expect(patches).toEqual([])
    expect(document.activeElement).toBe(button(w).element)
    expect(w.find('[data-test="title-input"]').exists()).toBe(false)
  })

  it('clicar fora fecha sem renomear', async () => {
    const w = mountHeader()
    await open(w)
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    await w.vm.$nextTick()
    expect(panel(w).exists()).toBe(false)
    expect(patches).toEqual([])
  })

  it('clicar no botão com o painel aberto fecha', async () => {
    const w = mountHeader()
    await open(w)
    await button(w).trigger('click')
    expect(panel(w).exists()).toBe(false)
  })

  it('uma resposta atrasada de um painel já fechado não reabre nada', async () => {
    let release: (r: Response) => void = () => {}
    const pending = new Promise<Response>((resolve) => { release = resolve })
    suggestAnswers = [() => pending]
    const w = mountHeader()
    await button(w).trigger('click')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
    release(jsonResponse({ suggestions: SUGGESTIONS }))
    await flushPromises()
    expect(panel(w).exists()).toBe(false)
  })
})
