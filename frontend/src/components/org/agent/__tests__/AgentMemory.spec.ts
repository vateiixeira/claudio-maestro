import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import AgentMemory from '../AgentMemory.vue'
import { useOrgStore } from '../../../../stores/org'
import { jsonResponse, routeFetch } from '../../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
})
afterEach(() => vi.unstubAllGlobals())

type Handlers = Parameters<typeof routeFetch>[0]

async function mountMemory(handlers: Handlers = {}, draft: string | null = null) {
  const fetch = routeFetch({ 'GET /api/agents/1/memory': () => jsonResponse({ text: 'Usar o filtro X.' }), ...handlers })
  vi.stubGlobal('fetch', fetch)
  const updates: (string | null)[] = []
  const wrapper = mount(AgentMemory, {
    props: {
      agentId: 1,
      draft,
      'onUpdate:draft': (value: string | null) => {
        updates.push(value)
        void wrapper.setProps({ draft: value })
      },
    },
    global: { plugins: [pinia] },
  })
  await flushPromises()
  return { wrapper, fetch, updates }
}

const q = (w: { get: (s: string) => { text: () => string } }, id: string) => w.get(`[data-test="${id}"]`)
const area = (w: Awaited<ReturnType<typeof mountMemory>>['wrapper']) => w.get<HTMLTextAreaElement>('[data-test="memory-text"]')

async function edit(wrapper: Awaited<ReturnType<typeof mountMemory>>['wrapper']) {
  await wrapper.get('[data-test="memory-edit"]').trigger('click')
}

describe('AgentMemory', () => {
  it('lê o markdown renderizado, sem campo de edição', async () => {
    const { wrapper } = await mountMemory({ 'GET /api/agents/1/memory': () => jsonResponse({ text: '## Ruído\n- item' }) })
    const view = wrapper.get('[data-test="memory-view"]')
    expect(view.get('h2').text()).toBe('Ruído')
    expect(view.get('li').text()).toBe('item')
    expect(wrapper.find('[data-test="memory-text"]').exists()).toBe(false)
  })

  it('escapa HTML cru', async () => {
    const { wrapper } = await mountMemory({ 'GET /api/agents/1/memory': () => jsonResponse({ text: '<script>alert(1)</script> oi' }) })
    const view = wrapper.get('[data-test="memory-view"]')
    expect(view.find('script').exists()).toBe(false)
    expect(view.text()).toContain('<script>alert(1)</script>')
  })

  it('memória vazia mostra o aviso', async () => {
    const { wrapper } = await mountMemory({ 'GET /api/agents/1/memory': () => jsonResponse({ text: '' }) })
    expect(q(wrapper, 'memory-empty').text()).toBe('O agente ainda não anotou nada.')
  })

  it('Editar mostra o campo com o texto salvo e o contador', async () => {
    const { wrapper } = await mountMemory()
    await edit(wrapper)
    expect(area(wrapper).element.value).toBe('Usar o filtro X.')
    expect(q(wrapper, 'memory-count').text()).toBe('16 de 4.000')
    expect(wrapper.get('[data-test="memory-save"]').attributes('disabled')).toBeDefined()
  })

  it('salva o texto, solta o rascunho e volta à leitura', async () => {
    const { wrapper, fetch, updates } = await mountMemory({ 'PUT /api/agents/1/memory': () => jsonResponse({ text: 'Novo' }) })
    await edit(wrapper)
    await area(wrapper).setValue('Novo')
    expect(updates.at(-1)).toBe('Novo')
    await wrapper.get('[data-test="memory-save"]').trigger('click')
    await flushPromises()
    const put = fetch.mock.calls.find(([, init]) => init?.method === 'PUT')
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({ text: 'Novo' })
    expect(updates.at(-1)).toBeNull()
    expect(wrapper.find('[data-test="memory-text"]').exists()).toBe(false)
    expect(q(wrapper, 'memory-view').text()).toBe('Novo')
  })

  it('Cancelar solta o rascunho e volta à leitura', async () => {
    const { wrapper, updates } = await mountMemory()
    await edit(wrapper)
    await area(wrapper).setValue('mudei')
    await wrapper.get('[data-test="memory-cancel"]').trigger('click')
    expect(updates.at(-1)).toBeNull()
    expect(wrapper.find('[data-test="memory-text"]').exists()).toBe(false)
    expect(q(wrapper, 'memory-view').text()).toBe('Usar o filtro X.')
  })

  it('montada com rascunho já abre editando', async () => {
    const { wrapper } = await mountMemory({}, 'rascunho')
    expect(area(wrapper).element.value).toBe('rascunho')
    expect(wrapper.get('[data-test="memory-save"]').attributes('disabled')).toBeUndefined()
  })

  it('o que foi digitado durante o salvamento fica como rascunho', async () => {
    let finish!: (r: Response) => void
    const { wrapper, updates } = await mountMemory({ 'PUT /api/agents/1/memory': () => new Promise<Response>((resolve) => { finish = resolve }) })
    await edit(wrapper)
    await area(wrapper).setValue('enviado')
    await wrapper.get('[data-test="memory-save"]').trigger('click')
    await area(wrapper).setValue('enviado e mais')
    finish(jsonResponse({ text: 'enviado' }))
    await flushPromises()
    expect(area(wrapper).element.value).toBe('enviado e mais')
    expect(updates.at(-1)).toBe('enviado e mais')
  })

  it('perto do limite mostra o medidor e o aviso', async () => {
    const { wrapper } = await mountMemory({ 'GET /api/agents/1/memory': () => jsonResponse({ text: 'a'.repeat(3995) }) })
    expect(q(wrapper, 'memory-count').text()).toBe('3.995 de 4.000')
    const meter = wrapper.get('[data-test="memory-meter"]')
    expect(meter.attributes('role')).toBe('meter')
    expect(meter.attributes('aria-valuenow')).toBe('3995')
    expect(meter.attributes('aria-valuemax')).toBe('4000')
    expect(meter.attributes('data-level')).toBe('near')
    expect(q(wrapper, 'memory-warning').text()).toBe('Quase cheia: sobram 5 caracteres. O que passar de 4.000 fica de fora da próxima execução.')
  })

  it('com 3.999 sobra 1 caractere, com 4.000 está cheia', async () => {
    const one = await mountMemory({ 'GET /api/agents/1/memory': () => jsonResponse({ text: 'a'.repeat(3999) }) })
    expect(q(one.wrapper, 'memory-warning').text()).toBe('Quase cheia: sobra 1 caractere. O que passar de 4.000 fica de fora da próxima execução.')
    const full = await mountMemory({ 'GET /api/agents/1/memory': () => jsonResponse({ text: 'a'.repeat(4000) }) })
    expect(q(full.wrapper, 'memory-warning').text()).toBe('Cheia: não sobra espaço. O que passar de 4.000 fica de fora da próxima execução.')
    expect(full.wrapper.get('[data-test="memory-meter"]').attributes('data-level')).toBe('near')
  })

  it('acima do limite avisa e não salva', async () => {
    const { wrapper } = await mountMemory({ 'GET /api/agents/1/memory': () => jsonResponse({ text: 'a'.repeat(4010) }) })
    expect(wrapper.get('[data-test="memory-meter"]').attributes('data-level')).toBe('over')
    expect(q(wrapper, 'memory-warning').text()).toBe('Passou do limite em 10 caracteres: a próxima execução só lê os primeiros 4.000.')
    await edit(wrapper)
    expect(wrapper.get('[data-test="memory-count"]').classes()).toContain('text-diff-del-fg')
    await area(wrapper).setValue('a'.repeat(4001))
    expect(wrapper.get('[data-test="memory-save"]').attributes('disabled')).toBeDefined()
  })

  it('longe do limite não há aviso', async () => {
    const { wrapper } = await mountMemory({ 'GET /api/agents/1/memory': () => jsonResponse({ text: 'a'.repeat(100) }) })
    expect(wrapper.get('[data-test="memory-meter"]').attributes('data-level')).toBe('ok')
    expect(wrapper.find('[data-test="memory-warning"]').exists()).toBe(false)
  })

  it('mostra o erro do salvamento e mantém o rascunho', async () => {
    const { wrapper } = await mountMemory({ 'PUT /api/agents/1/memory': () => jsonResponse({ detail: 'A memória passa do limite.' }, 422) })
    await edit(wrapper)
    await area(wrapper).setValue('Novo')
    await wrapper.get('[data-test="memory-save"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="memory-error"]').attributes('role')).toBe('alert')
    expect(wrapper.get('[data-test="memory-error"]').text()).toContain('A memória passa do limite.')
    expect(area(wrapper).element.value).toBe('Novo')
  })

  it('relê a memória quando o agente muda e atualiza a leitura', async () => {
    let text = 'Antes'
    const { wrapper } = await mountMemory({ 'GET /api/agents/1/memory': () => jsonResponse({ text }) })
    text = 'Depois'
    useOrgStore(pinia).changes = { 1: 1 }
    await flushPromises()
    expect(q(wrapper, 'memory-view').text()).toBe('Depois')
  })

  it('o agente reescrevendo não apaga o rascunho aberto', async () => {
    let text = 'Antes'
    const { wrapper } = await mountMemory({ 'GET /api/agents/1/memory': () => jsonResponse({ text }) })
    await edit(wrapper)
    await area(wrapper).setValue('meu rascunho')
    text = 'Depois'
    useOrgStore(pinia).changes = { 1: 1 }
    await flushPromises()
    expect(area(wrapper).element.value).toBe('meu rascunho')
  })

  it('se a leitura falha, bloqueia Editar e mostra Tentar de novo', async () => {
    let fail = true
    const { wrapper } = await mountMemory({
      'GET /api/agents/1/memory': () => (fail ? jsonResponse({ detail: 'Falhou ao ler.' }, 500) : jsonResponse({ text: 'Lida.' })),
    })
    expect(wrapper.get('[data-test="memory-error"]').text()).toContain('Falhou ao ler.')
    expect(wrapper.get('[data-test="memory-edit"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-test="memory-empty"]').exists()).toBe(false)
    fail = false
    await wrapper.get('[data-test="memory-retry"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="memory-error"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="memory-retry"]').exists()).toBe(false)
    expect(q(wrapper, 'memory-view').text()).toBe('Lida.')
    expect(wrapper.get('[data-test="memory-edit"]').attributes('disabled')).toBeUndefined()
  })

  it('com rascunho e leitura falha, Salvar fica desabilitado', async () => {
    const { wrapper, fetch } = await mountMemory({ 'GET /api/agents/1/memory': () => jsonResponse({ detail: 'Falhou ao ler.' }, 500) }, 'rascunho')
    expect(wrapper.get('[data-test="memory-save"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-test="memory-save"]').trigger('click')
    expect(fetch.mock.calls.some(([, init]) => init?.method === 'PUT')).toBe(false)
  })
})
