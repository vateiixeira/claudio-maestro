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

describe('AgentMemory', () => {
  it('carrega o texto e mostra o contador', async () => {
    const { wrapper } = await mountMemory()
    expect(wrapper.get<HTMLTextAreaElement>('[data-test="memory-text"]').element.value).toBe('Usar o filtro X.')
    expect(wrapper.get('[data-test="memory-count"]').text()).toBe('16 / 4.000')
    expect(wrapper.get('[data-test="memory-save"]').attributes('disabled')).toBeDefined()
  })

  it('salva o texto e solta o rascunho', async () => {
    const { wrapper, fetch, updates } = await mountMemory({ 'PUT /api/agents/1/memory': () => jsonResponse({ text: 'Novo' }) })
    await wrapper.get('[data-test="memory-text"]').setValue('Novo')
    expect(updates.at(-1)).toBe('Novo')
    await wrapper.get('[data-test="memory-save"]').trigger('click')
    await flushPromises()
    const put = fetch.mock.calls.find(([, init]) => init?.method === 'PUT')
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({ text: 'Novo' })
    expect(updates.at(-1)).toBeNull()
    expect(wrapper.get<HTMLTextAreaElement>('[data-test="memory-text"]').element.value).toBe('Novo')
  })

  it('o rascunho do painel aparece no lugar do texto salvo', async () => {
    const { wrapper } = await mountMemory({}, 'rascunho')
    expect(wrapper.get<HTMLTextAreaElement>('[data-test="memory-text"]').element.value).toBe('rascunho')
    expect(wrapper.get('[data-test="memory-save"]').attributes('disabled')).toBeUndefined()
  })

  it('o que foi digitado durante o salvamento fica como rascunho', async () => {
    let finish!: (r: Response) => void
    const { wrapper, updates } = await mountMemory({ 'PUT /api/agents/1/memory': () => new Promise<Response>((resolve) => { finish = resolve }) })
    await wrapper.get('[data-test="memory-text"]').setValue('enviado')
    await wrapper.get('[data-test="memory-save"]').trigger('click')
    await wrapper.get('[data-test="memory-text"]').setValue('enviado e mais')
    finish(jsonResponse({ text: 'enviado' }))
    await flushPromises()
    expect(wrapper.get<HTMLTextAreaElement>('[data-test="memory-text"]').element.value).toBe('enviado e mais')
    expect(updates.at(-1)).toBe('enviado e mais')
  })

  it('acima do limite não salva', async () => {
    const { wrapper } = await mountMemory()
    await wrapper.get('[data-test="memory-text"]').setValue('a'.repeat(4001))
    expect(wrapper.get('[data-test="memory-count"]').classes()).toContain('text-diff-del-fg')
    expect(wrapper.get('[data-test="memory-save"]').attributes('disabled')).toBeDefined()
  })

  it('mostra o erro do salvamento e mantém o rascunho', async () => {
    const { wrapper } = await mountMemory({ 'PUT /api/agents/1/memory': () => jsonResponse({ detail: 'A memória passa do limite.' }, 422) })
    await wrapper.get('[data-test="memory-text"]').setValue('Novo')
    await wrapper.get('[data-test="memory-save"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="memory-error"]').attributes('role')).toBe('alert')
    expect(wrapper.get('[data-test="memory-error"]').text()).toContain('A memória passa do limite.')
    expect(wrapper.get<HTMLTextAreaElement>('[data-test="memory-text"]').element.value).toBe('Novo')
  })

  it('relê a memória quando o agente muda e não há rascunho', async () => {
    let text = 'Antes'
    const { wrapper } = await mountMemory({ 'GET /api/agents/1/memory': () => jsonResponse({ text }) })
    text = 'Depois'
    useOrgStore(pinia).changes = { 1: 1 }
    await flushPromises()
    expect(wrapper.get<HTMLTextAreaElement>('[data-test="memory-text"]').element.value).toBe('Depois')
  })
})
