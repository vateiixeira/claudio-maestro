import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import AgentDefinition from '../AgentDefinition.vue'
import type { DefinitionDraft } from '../helpers'
import { useOrgStore } from '../../../../stores/org'
import { jsonResponse, makeAgent, routeFetch } from '../../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

const FILE = '---\nname: CTO\n---\nCoordena.\n'

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  useOrgStore(pinia).agents = [makeAgent({ id: 1 })]
})
afterEach(() => vi.unstubAllGlobals())

type Handlers = Parameters<typeof routeFetch>[0]

async function mountEditor(handlers: Handlers = {}, draft: DefinitionDraft | null = null) {
  const fetch = routeFetch({
    'GET /api/agents/1/definition': () => jsonResponse({ text: FILE, hash: 'h1' }),
    'GET /api/agents': () => jsonResponse([makeAgent({ id: 1 })]),
    ...handlers,
  })
  vi.stubGlobal('fetch', fetch)
  const updates: (DefinitionDraft | null)[] = []
  const wrapper = mount(AgentDefinition, {
    props: {
      agentId: 1,
      draft,
      'onUpdate:draft': (value: DefinitionDraft | null) => {
        updates.push(value)
        void wrapper.setProps({ draft: value })
      },
    },
    global: { plugins: [pinia] },
  })
  await flushPromises()
  return { wrapper, fetch, updates }
}

const area = (w: Awaited<ReturnType<typeof mountEditor>>['wrapper']) => w.get<HTMLTextAreaElement>('[data-test="definition-text"]')
const bodies = (fetch: ReturnType<typeof routeFetch>, method: string, url: string) =>
  fetch.mock.calls.filter(([u, init]) => u === url && (init?.method ?? 'GET') === method).map(([, init]) => JSON.parse(String(init?.body)))

describe('AgentDefinition', () => {
  it('carrega o arquivo e mostra o contador de bytes', async () => {
    const { wrapper } = await mountEditor()
    expect(area(wrapper).element.value).toBe(FILE)
    expect(area(wrapper).classes()).toContain('font-mono')
    expect(wrapper.get('[data-test="definition-count"]').text()).toBe(`${new TextEncoder().encode(FILE).length} / 100.000 bytes`)
    expect(wrapper.get('[data-test="definition-save"]').attributes('disabled')).toBeDefined()
  })

  it('a ajuda fixa lista os 10 campos do cabeçalho', async () => {
    const { wrapper } = await mountEditor()
    const keys = wrapper.findAll('[data-test="definition-help"] li').map((li) => li.get('code').text())
    expect(keys).toEqual(['name', 'description', 'model', 'effort', 'permissionMode', 'disallowedTools', 'skills', 'addDirs', 'worktree', 'maxRunMinutes'])
    expect(wrapper.get('[data-test="definition-help"]').text()).toContain('bypassPermissions')
  })

  it('salvar envia o texto com o hash e recarrega os agentes', async () => {
    const { wrapper, fetch, updates } = await mountEditor({
      'PUT /api/agents/1/definition': () => jsonResponse({ text: 'novo', hash: 'h2' }),
      'GET /api/agents': () => jsonResponse([makeAgent({ id: 1, name: 'Novo nome', description: 'Outra' })]),
    })
    await area(wrapper).setValue('novo')
    expect(wrapper.get('[data-test="definition-save"]').attributes('disabled')).toBeUndefined()
    await wrapper.get('[data-test="definition-save"]').trigger('click')
    await flushPromises()
    expect(bodies(fetch, 'PUT', '/api/agents/1/definition')).toEqual([{ text: 'novo', hash: 'h1' }])
    expect(fetch.mock.calls.some(([u, init]) => u === '/api/agents' && (init?.method ?? 'GET') === 'GET')).toBe(true)
    expect(useOrgStore(pinia).byId(1)?.name).toBe('Novo nome')
    expect(updates.at(-1)).toBeNull()
    expect(area(wrapper).element.value).toBe('novo')
    expect(wrapper.get('[data-test="definition-save"]').attributes('disabled')).toBeDefined()
    // The next save is based on the hash that came back.
    await area(wrapper).setValue('novo 2')
    await wrapper.get('[data-test="definition-save"]').trigger('click')
    await flushPromises()
    expect(bodies(fetch, 'PUT', '/api/agents/1/definition')[1]).toEqual({ text: 'novo 2', hash: 'h2' })
  })

  it('mostra o erro de validação na linha e mantém o rascunho', async () => {
    const { wrapper, updates } = await mountEditor({
      'PUT /api/agents/1/definition': () => jsonResponse({ detail: 'O campo `effort` precisa ser um de: low, medium.', field: 'effort', line: 3 }, 422),
    })
    const broken = '---\nname: CTO\neffort: enorme\n---\nCoordena.\n'
    await area(wrapper).setValue(broken)
    await wrapper.get('[data-test="definition-save"]').trigger('click')
    await flushPromises()
    const alert = wrapper.get('[data-test="definition-error"]')
    expect(alert.attributes('role')).toBe('alert')
    expect(alert.text()).toContain('O campo `effort` precisa ser um de: low, medium.')
    expect(alert.text()).toContain('linha 3')
    expect(area(wrapper).element.value).toBe(broken)
    expect(updates.at(-1)).toEqual({ text: broken, hash: 'h1' })
    // The draft is still there to save again.
    expect(wrapper.get('[data-test="definition-save"]').attributes('disabled')).toBeUndefined()
  })

  it('erro sem linha mostra só a mensagem', async () => {
    const { wrapper } = await mountEditor({
      'PUT /api/agents/1/definition': () => jsonResponse({ detail: 'O AGENT.md passa de 100 KB; reduza o texto.', field: null, line: null }, 422),
    })
    await area(wrapper).setValue('x')
    await wrapper.get('[data-test="definition-save"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="definition-error"]').text()).not.toContain('linha')
  })

  it('409 pede recarregar e Recarregar traz a versão atual', async () => {
    let served = FILE
    const { wrapper, updates } = await mountEditor({
      'GET /api/agents/1/definition': () => jsonResponse({ text: served, hash: served === FILE ? 'h1' : 'h9' }),
      'PUT /api/agents/1/definition': () => jsonResponse({ detail: 'O AGENT.md mudou desde que você o abriu.' }, 409),
    })
    await area(wrapper).setValue('meu rascunho')
    await wrapper.get('[data-test="definition-save"]').trigger('click')
    await flushPromises()
    const alert = wrapper.get('[data-test="definition-error"]')
    expect(alert.text()).toContain('O arquivo mudou fora daqui. Recarregue para ver a versão atual.')
    expect(area(wrapper).element.value).toBe('meu rascunho')
    served = '---\nname: Outro\n---\nTexto de fora.\n'
    await wrapper.get('[data-test="definition-reload"]').trigger('click')
    await flushPromises()
    expect(area(wrapper).element.value).toBe(served)
    expect(wrapper.find('[data-test="definition-error"]').exists()).toBe(false)
    expect(updates.at(-1)).toBeNull()
  })

  it('o que foi digitado durante o salvamento fica como rascunho', async () => {
    let finish!: (r: Response) => void
    const { wrapper, updates } = await mountEditor({
      'PUT /api/agents/1/definition': () => new Promise<Response>((resolve) => { finish = resolve }),
    })
    await area(wrapper).setValue('enviado')
    await wrapper.get('[data-test="definition-save"]').trigger('click')
    await area(wrapper).setValue('enviado e mais um pouco')
    finish(jsonResponse({ text: 'enviado', hash: 'h2' }))
    await flushPromises()
    expect(area(wrapper).element.value).toBe('enviado e mais um pouco')
    expect(updates.at(-1)).toEqual({ text: 'enviado e mais um pouco', hash: 'h2' })
    expect(wrapper.get('[data-test="definition-save"]').attributes('disabled')).toBeUndefined()
  })

  it('texto acima do limite desabilita o Salvar', async () => {
    const { wrapper } = await mountEditor()
    await area(wrapper).setValue('a'.repeat(100_001))
    expect(wrapper.get('[data-test="definition-count"]').classes()).toContain('text-diff-del-fg')
    expect(wrapper.get('[data-test="definition-save"]').attributes('disabled')).toBeDefined()
  })

  it('o rascunho do painel vence o arquivo e mantém o hash em que foi baseado', async () => {
    const { wrapper, fetch } = await mountEditor(
      {
        'GET /api/agents/1/definition': () => jsonResponse({ text: FILE, hash: 'h-novo' }),
        'PUT /api/agents/1/definition': () => jsonResponse({ detail: 'mudou' }, 409),
      },
      { text: 'rascunho antigo', hash: 'h-velho' },
    )
    expect(area(wrapper).element.value).toBe('rascunho antigo')
    await wrapper.get('[data-test="definition-save"]').trigger('click')
    await flushPromises()
    expect(bodies(fetch, 'PUT', '/api/agents/1/definition')).toEqual([{ text: 'rascunho antigo', hash: 'h-velho' }])
  })

  it('mostra o erro da definição que o agente já traz e some quando ela é salva', async () => {
    useOrgStore(pinia).agents = [makeAgent({ id: 1, definition_error: 'Falta o campo name na linha 2.' })]
    const { wrapper } = await mountEditor({
      'PUT /api/agents/1/definition': () => jsonResponse({ text: FILE, hash: 'h2' }),
    })
    const alert = wrapper.get('[data-test="definition-current-error"]')
    expect(alert.attributes('role')).toBe('alert')
    expect(alert.text()).toContain('Falta o campo name na linha 2.')
  })

  it('arquivo que não abre mostra o motivo e não deixa salvar às cegas', async () => {
    const { wrapper } = await mountEditor({
      'GET /api/agents/1/definition': () => jsonResponse({ detail: 'A pasta do agente não existe mais.' }, 404),
    })
    expect(wrapper.get('[data-test="definition-load-error"]').text()).toContain('A pasta do agente não existe mais.')
    expect(wrapper.find('[data-test="definition-text"]').exists()).toBe(false)
  })
})
