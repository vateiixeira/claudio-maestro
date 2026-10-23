import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import AgentDetail from '../AgentDetail.vue'
import OptionMenu from '../../session/OptionMenu.vue'
import { createAppRouter } from '../../../router'
import { jsonResponse, makeProject, makeSpecialist, makeSpecialistRun, routeFetch } from '../../../test/factories'
import { useProjectsStore } from '../../../stores/projects'
import { useSpecialistsStore } from '../../../stores/specialists'
import type { Specialist, SpecialistItem } from '../../../types/api'

vi.mock('../../../stores/realtime', () => ({ loadEverything: vi.fn(() => Promise.resolve()) }))

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  useProjectsStore().projects = [makeProject({ id: 1, name: 'loja' }), makeProject({ id: 2, name: 'api' })]
})
afterEach(() => vi.unstubAllGlobals())

type Routes = Record<string, () => Response | Promise<Response>>
const baseRoutes = (over: Routes = {}): Routes => ({
  'GET /api/models': () => jsonResponse([]),
  'GET /api/specialists/1/skill': () => jsonResponse({ text: '---\nname: sentry\n---\nCorpo' }),
  'GET /api/specialists/1/learnings': () => jsonResponse({ text: 'Usar o filtro X.' }),
  'GET /api/specialists/1/secrets': () => jsonResponse({ names: ['SENTRY_TOKEN'] }),
  'GET /api/specialists/1/items': () => jsonResponse([]),
  'GET /api/specialists/1/runs?limit=50': () => jsonResponse([]),
  ...over,
})

async function mountDetail(agent: Specialist = makeSpecialist(), routes: Routes = {}) {
  const fetch = routeFetch(baseRoutes(routes))
  vi.stubGlobal('fetch', fetch)
  useSpecialistsStore().list = [agent]
  const router = createAppRouter(createMemoryHistory())
  await router.push(`/agentes/${agent.id}`)
  const wrapper = mount(AgentDetail, { props: { agent }, global: { plugins: [pinia, router] }, attachTo: document.body })
  await flushPromises()
  return { wrapper, fetch, router }
}
const bodies = (fetch: ReturnType<typeof routeFetch>, method: string, url: string) =>
  fetch.mock.calls.filter(([u, init]) => u === url && (init?.method ?? 'GET') === method).map(([, init]) => JSON.parse(String(init?.body)))

describe('AgentDetail', () => {
  it('mostra as seções na ordem do desenho', async () => {
    const { wrapper } = await mountDetail()
    expect(wrapper.findAll('[data-test="section-title"]').map((t) => t.text().toLowerCase())).toEqual([
      'skill', 'pasta e projetos', 'autonomia', 'horários', 'fechamento', 'modelo e raciocínio', 'segredos',
      'mcps na última execução', 'aprendizados', 'registro', 'execuções',
    ])
    expect(wrapper.get('[data-test="agent-name"]').text()).toBe('Sentry')
    expect(wrapper.get('[data-test="agent-description"]').text()).toBe('Trata os erros novos do Sentry')
  })

  describe('skill', () => {
    it('carrega o texto e salva o que foi editado', async () => {
      const { wrapper, fetch } = await mountDetail(makeSpecialist(), {
        'PUT /api/specialists/1/skill': () => jsonResponse({ name: 'sentry', description: 'x' }),
      })
      const area = wrapper.get<HTMLTextAreaElement>('[data-test="skill-text"]')
      expect(area.element.value).toContain('Corpo')
      expect(area.classes()).toContain('font-mono')
      await area.setValue('---\nname: sentry\n---\nNovo')
      await wrapper.get('[data-test="skill-save"]').trigger('click')
      await flushPromises()
      expect(bodies(fetch, 'PUT', '/api/specialists/1/skill')).toEqual([{ text: '---\nname: sentry\n---\nNovo' }])
      expect(wrapper.find('[data-test="skill-error"]').exists()).toBe(false)
    })

    it('com erro da API, mantém o texto e mostra a mensagem embaixo', async () => {
      const { wrapper } = await mountDetail(makeSpecialist(), {
        'PUT /api/specialists/1/skill': () => jsonResponse({ detail: 'O SKILL.md precisa de um cabeçalho com name e description.' }, 422),
      })
      const area = wrapper.get<HTMLTextAreaElement>('[data-test="skill-text"]')
      await area.setValue('texto sem cabeçalho')
      await wrapper.get('[data-test="skill-save"]').trigger('click')
      await flushPromises()
      expect(area.element.value).toBe('texto sem cabeçalho')
      expect(wrapper.get('[data-test="skill-error"]').text()).toBe('O SKILL.md precisa de um cabeçalho com name e description.')
    })

    it('"Salvar" só liga quando o texto mudou', async () => {
      const { wrapper } = await mountDetail()
      const save = wrapper.get('[data-test="skill-save"]')
      expect(save.attributes('disabled')).toBeDefined()
      await wrapper.get('[data-test="skill-text"]').setValue('outro')
      expect(save.attributes('disabled')).toBeUndefined()
    })
  })

  describe('rodar agora', () => {
    it('abre a caixa com o texto do agente, manda o texto editado e abre a sessão criada', async () => {
      const { wrapper, fetch, router } = await mountDetail(makeSpecialist({ run_text: 'Siga a skill.' }), {
        'POST /api/specialists/1/run': () => jsonResponse(makeSpecialistRun({ id: 3, session_id: 's42' }), 202),
      })
      await wrapper.get('[data-test="run-now"]').trigger('click')
      const area = wrapper.get<HTMLTextAreaElement>('[data-test="run-text"]')
      expect(area.element.value).toBe('Siga a skill.')
      await area.setValue('Só os de hoje.')
      await wrapper.get('[data-test="confirm-ok"]').trigger('click')
      await flushPromises()
      expect(bodies(fetch, 'POST', '/api/specialists/1/run')).toEqual([{ text: 'Só os de hoje.' }])
      expect(router.currentRoute.value.fullPath).toBe('/sessions/s42')
    })

    it('cancelar não chama a API', async () => {
      const { wrapper, fetch } = await mountDetail()
      await wrapper.get('[data-test="run-now"]').trigger('click')
      await wrapper.get('[data-test="confirm-cancel"]').trigger('click')
      expect(wrapper.find('[data-test="run-text"]').exists()).toBe(false)
      expect(bodies(fetch, 'POST', '/api/specialists/1/run')).toEqual([])
    })

    it('execução que já nasceu falha, sem sessão: não navega e mostra o motivo', async () => {
      const { wrapper, router } = await mountDetail(makeSpecialist(), {
        'POST /api/specialists/1/run': () => jsonResponse(makeSpecialistRun({ session_id: null, outcome: 'failed', reason: 'A pasta do projeto não está disponível.' }), 202),
      })
      await wrapper.get('[data-test="run-now"]').trigger('click')
      await wrapper.get('[data-test="confirm-ok"]').trigger('click')
      await flushPromises()
      expect(router.currentRoute.value.fullPath).toBe('/agentes/1')
      expect(wrapper.get('[data-test="action-error"]').text()).toContain('A pasta do projeto não está disponível.')
    })

    it('mostra o erro da API como veio', async () => {
      const { wrapper } = await mountDetail(makeSpecialist(), {
        'POST /api/specialists/1/run': () => jsonResponse({ detail: 'Agente não encontrado.' }, 404),
      })
      await wrapper.get('[data-test="run-now"]').trigger('click')
      await wrapper.get('[data-test="confirm-ok"]').trigger('click')
      await flushPromises()
      expect(wrapper.get('[data-test="action-error"]').text()).toContain('Agente não encontrado.')
    })
  })

  describe('autonomia e ações para fora', () => {
    it('os padrões de fábrica não têm botão de remover; os acrescentados têm', async () => {
      const { wrapper } = await mountDetail(makeSpecialist({ outward_patterns: ['docker push'], always_ask_patterns: ['rm -rf'] }))
      const defaults = wrapper.findAll('[data-test="outward-default"]')
      expect(defaults.map((d) => d.text())).toContain('git push')
      expect(defaults.every((d) => d.find('button').exists())).toBe(false)
      const custom = wrapper.findAll('[data-test="outward-custom"]')
      expect(custom.map((d) => d.text())).toEqual(['docker push'])
      expect(custom[0]!.find('[data-test="pattern-remove"]').exists()).toBe(true)
      expect(wrapper.findAll('[data-test="always-default"]').map((d) => d.text())).toEqual(['gh pr merge'])
      expect(wrapper.findAll('[data-test="always-default"] button')).toHaveLength(0)
      expect(wrapper.findAll('[data-test="always-custom"]').map((d) => d.text())).toEqual(['rm -rf'])
    })

    it('acrescenta e remove padrões salvando a lista inteira', async () => {
      const agent = makeSpecialist({ outward_patterns: ['docker push'] })
      const { wrapper, fetch } = await mountDetail(agent, {
        'PATCH /api/specialists/1': () => jsonResponse({ ...agent, outward_patterns: ['docker push', 'npm publish'] }),
      })
      await wrapper.get('[data-test="outward-input"]').setValue('  npm publish ')
      await wrapper.get('[data-test="outward-add"]').trigger('click')
      await flushPromises()
      expect(bodies(fetch, 'PATCH', '/api/specialists/1')).toEqual([{ outward_patterns: ['docker push', 'npm publish'] }])
      await wrapper.get('[data-test="outward-custom"] [data-test="pattern-remove"]').trigger('click')
      await flushPromises()
      expect(bodies(fetch, 'PATCH', '/api/specialists/1')[1]).toEqual({ outward_patterns: [] })
    })

    it('não deixa acrescentar um padrão de fábrica de novo nem vazio', async () => {
      const { wrapper, fetch } = await mountDetail()
      await wrapper.get('[data-test="outward-input"]').setValue('git push')
      await wrapper.get('[data-test="outward-add"]').trigger('click')
      await wrapper.get('[data-test="outward-input"]').setValue('   ')
      await wrapper.get('[data-test="outward-add"]').trigger('click')
      await flushPromises()
      expect(bodies(fetch, 'PATCH', '/api/specialists/1')).toEqual([])
    })

    it('com a API recusando, os botões voltam à autonomia do agente', async () => {
      const { wrapper } = await mountDetail(makeSpecialist(), {
        'PATCH /api/specialists/1': () => jsonResponse({ detail: 'Recusado.' }, 422),
      })
      await wrapper.get('[data-test="autonomy-full"]').setValue(true)
      await flushPromises()
      expect(wrapper.get<HTMLInputElement>('[data-test="autonomy-ask"]').element.checked).toBe(true)
      expect(wrapper.get<HTMLInputElement>('[data-test="autonomy-full"]').element.checked).toBe(false)
      expect(wrapper.get('[data-test="action-error"]').text()).toContain('Recusado.')
    })

    it('troca a autonomia', async () => {
      const agent = makeSpecialist()
      const { wrapper, fetch } = await mountDetail(agent, {
        'PATCH /api/specialists/1': () => jsonResponse({ ...agent, autonomy: 'full' }),
      })
      expect(wrapper.get<HTMLInputElement>('[data-test="autonomy-ask"]').element.checked).toBe(true)
      expect(wrapper.text()).toContain('Pede ok antes de agir para fora')
      expect(wrapper.text()).toContain('Vai até o fim')
      await wrapper.get('[data-test="autonomy-full"]').setValue(true)
      await flushPromises()
      expect(bodies(fetch, 'PATCH', '/api/specialists/1')).toEqual([{ autonomy: 'full' }])
    })
  })

  describe('horários', () => {
    it('adiciona uma linha, escolhe dias e hora e salva', async () => {
      const agent = makeSpecialist()
      const { wrapper, fetch } = await mountDetail(agent, {
        'PATCH /api/specialists/1': () => jsonResponse({ ...agent, schedules: [{ id: 1, days: '135', time: '09:30', last_fired_at: null }] }),
      })
      await wrapper.get('[data-test="schedule-add"]').trigger('click')
      const row = wrapper.get('[data-test="schedule-row"]')
      expect(row.findAll('[data-test="day"]').map((d) => d.text())).toEqual(['S', 'T', 'Q', 'Q', 'S', 'S', 'D'])
      // a linha nova começa com todos os dias ligados: desliga T, Q, S e D
      for (const index of [1, 3, 5, 6]) await row.findAll('[data-test="day"]')[index]!.trigger('click')
      await row.get('[data-test="schedule-time"]').setValue('09:30')
      await wrapper.get('[data-test="schedule-save"]').trigger('click')
      await flushPromises()
      const sent = bodies(fetch, 'PATCH', '/api/specialists/1')[0]
      expect(sent.schedules).toEqual([{ days: '135', time: '09:30' }])
    })

    it('mostra os horários do agente e remove uma linha', async () => {
      const agent = makeSpecialist({ schedules: [{ id: 1, days: '12345', time: '08:40', last_fired_at: null }, { id: 2, days: '67', time: '20:00', last_fired_at: null }] })
      const { wrapper, fetch } = await mountDetail(agent, {
        'PATCH /api/specialists/1': () => jsonResponse({ ...agent, schedules: [agent.schedules[1]!] }),
      })
      const rows = wrapper.findAll('[data-test="schedule-row"]')
      expect(rows).toHaveLength(2)
      expect(rows[0]!.get<HTMLInputElement>('[data-test="schedule-time"]').element.value).toBe('08:40')
      expect(rows[0]!.findAll('[data-test="day"]').map((d) => d.attributes('aria-pressed'))).toEqual(['true', 'true', 'true', 'true', 'true', 'false', 'false'])
      await rows[0]!.get('[data-test="schedule-remove"]').trigger('click')
      await wrapper.get('[data-test="schedule-save"]').trigger('click')
      await flushPromises()
      expect(bodies(fetch, 'PATCH', '/api/specialists/1')[0].schedules).toEqual([{ days: '67', time: '20:00' }])
    })

    it('o erro 422 dos horários aparece como veio', async () => {
      const { wrapper } = await mountDetail(makeSpecialist(), {
        'PATCH /api/specialists/1': () => jsonResponse({ detail: 'Os dias do horário devem ser números de 1 (segunda) a 7 (domingo).' }, 422),
      })
      await wrapper.get('[data-test="schedule-add"]').trigger('click')
      await wrapper.get('[data-test="schedule-save"]').trigger('click')
      await flushPromises()
      expect(wrapper.get('[data-test="schedule-error"]').text()).toBe('Os dias do horário devem ser números de 1 (segunda) a 7 (domingo).')
      expect(wrapper.findAll('[data-test="schedule-row"]')).toHaveLength(1)
    })

    it('o interruptor "Horários ligados" salva enabled', async () => {
      const agent = makeSpecialist()
      const { wrapper, fetch } = await mountDetail(agent, {
        'PATCH /api/specialists/1': () => jsonResponse({ ...agent, enabled: false }),
      })
      const toggle = wrapper.get('[data-test="agent-enabled"]')
      expect(toggle.attributes('aria-checked')).toBe('true')
      expect(wrapper.text()).toContain('Horários ligados')
      await toggle.trigger('click')
      await flushPromises()
      expect(bodies(fetch, 'PATCH', '/api/specialists/1')).toEqual([{ enabled: false }])
    })
  })

  describe('pasta e projetos', () => {
    it('troca o projeto de origem e acrescenta projetos adicionais', async () => {
      const agent = makeSpecialist()
      const { wrapper, fetch } = await mountDetail(agent, {
        'PATCH /api/specialists/1': () => jsonResponse(agent),
      })
      await wrapper.get('[data-test="project-select"]').setValue('2')
      await flushPromises()
      expect(bodies(fetch, 'PATCH', '/api/specialists/1')).toEqual([{ project_id: 2 }])
      // o projeto de origem não é oferecido como adicional
      const options = wrapper.findAll('[data-test="extra-project-select"] option').map((o) => o.text())
      expect(options).not.toContain('loja')
      expect(options).toContain('api')
      await wrapper.get('[data-test="extra-project-select"]').setValue('2')
      await flushPromises()
      expect(bodies(fetch, 'PATCH', '/api/specialists/1')[1]).toEqual({ extra_project_ids: [2] })
    })

    it('lista os adicionais com botão de remover', async () => {
      const agent = makeSpecialist({ extra_project_ids: [2] })
      const { wrapper, fetch } = await mountDetail(agent, { 'PATCH /api/specialists/1': () => jsonResponse(agent) })
      expect(wrapper.findAll('[data-test="extra-project"]').map((e) => e.text())).toEqual(['api'])
      await wrapper.get('[data-test="extra-project-remove"]').trigger('click')
      await flushPromises()
      expect(bodies(fetch, 'PATCH', '/api/specialists/1')).toEqual([{ extra_project_ids: [] }])
    })
  })

  describe('fechamento', () => {
    it('com a API recusando, a caixa volta ao valor do agente', async () => {
      const { wrapper } = await mountDetail(makeSpecialist({ close_by_check: false }), {
        'PATCH /api/specialists/1': () => jsonResponse({ detail: 'Recusado.' }, 422),
      })
      await wrapper.get('[data-test="close-by-check"]').setValue(true)
      await flushPromises()
      expect(wrapper.get<HTMLInputElement>('[data-test="close-by-check"]').element.checked).toBe(false)
    })

    it('liga "Fechar sozinha quando a verificação disser que pode"', async () => {
      const agent = makeSpecialist()
      const { wrapper, fetch } = await mountDetail(agent, { 'PATCH /api/specialists/1': () => jsonResponse({ ...agent, close_by_check: true }) })
      expect(wrapper.text()).toContain('Fechar sozinha quando a verificação disser que pode')
      await wrapper.get('[data-test="close-by-check"]').setValue(true)
      await flushPromises()
      expect(bodies(fetch, 'PATCH', '/api/specialists/1')).toEqual([{ close_by_check: true }])
    })
  })

  describe('segredos', () => {
    it('lista só os nomes, sem campo com valor', async () => {
      const { wrapper } = await mountDetail()
      expect(wrapper.findAll('[data-test="secret-name"]').map((s) => s.text())).toEqual(['SENTRY_TOKEN'])
      const inputs = wrapper.findAll('[data-test="secrets"] input')
      expect(inputs.every((i) => i.attributes('type') === 'password' || i.attributes('data-test') === 'secret-new-name')).toBe(true)
      expect(inputs.every((i) => (i.element as HTMLInputElement).value === '')).toBe(true)
    })

    it('Enter nos campos envia o formulário: o botão é de envio', async () => {
      const { wrapper, fetch } = await mountDetail(makeSpecialist(), {
        'PUT /api/specialists/1/secrets': () => jsonResponse({ names: ['SENTRY_TOKEN', 'X'] }),
      })
      expect(wrapper.get('[data-test="secret-add"]').attributes('type')).toBe('submit')
      await wrapper.get('[data-test="secret-new-name"]').setValue('X')
      await wrapper.get('[data-test="secret-new-value"]').setValue('v')
      await wrapper.get('[data-test="secrets"] form').trigger('submit')
      await flushPromises()
      expect(bodies(fetch, 'PUT', '/api/specialists/1/secrets')).toEqual([{ values: { X: 'v' } }])
    })

    it('adiciona um segredo: manda o valor, limpa os campos e não o mostra depois', async () => {
      const { wrapper, fetch } = await mountDetail(makeSpecialist(), {
        'PUT /api/specialists/1/secrets': () => jsonResponse({ names: ['SENTRY_TOKEN', 'DB_URL'] }),
      })
      await wrapper.get('[data-test="secret-new-name"]').setValue('DB_URL')
      const value = wrapper.get<HTMLInputElement>('[data-test="secret-new-value"]')
      expect(value.attributes('type')).toBe('password')
      await value.setValue('postgres://segredo-super-secreto')
      await wrapper.get('[data-test="secret-add"]').trigger('click')
      await flushPromises()
      expect(bodies(fetch, 'PUT', '/api/specialists/1/secrets')).toEqual([{ values: { DB_URL: 'postgres://segredo-super-secreto' } }])
      expect(wrapper.findAll('[data-test="secret-name"]').map((s) => s.text())).toEqual(['SENTRY_TOKEN', 'DB_URL'])
      expect(value.element.value).toBe('')
      expect(wrapper.html()).not.toContain('segredo-super-secreto')
      expect(document.body.innerHTML).not.toContain('segredo-super-secreto')
    })

    it('troca o valor de um segredo existente e remove outro', async () => {
      const { wrapper, fetch } = await mountDetail(makeSpecialist(), {
        'PUT /api/specialists/1/secrets': () => jsonResponse({ names: ['SENTRY_TOKEN'] }),
      })
      await wrapper.get('[data-test="secret-change"]').trigger('click')
      await wrapper.get('[data-test="secret-change-value"]').setValue('novo-valor')
      await wrapper.get('[data-test="secret-change-save"]').trigger('click')
      await flushPromises()
      expect(bodies(fetch, 'PUT', '/api/specialists/1/secrets')[0]).toEqual({ values: { SENTRY_TOKEN: 'novo-valor' } })
      expect(wrapper.html()).not.toContain('novo-valor')
      await wrapper.get('[data-test="secret-remove"]').trigger('click')
      await flushPromises()
      expect(bodies(fetch, 'PUT', '/api/specialists/1/secrets')[1]).toEqual({ values: { SENTRY_TOKEN: null } })
    })

    it('o erro da API aparece sem repetir o valor digitado', async () => {
      const { wrapper } = await mountDetail(makeSpecialist(), {
        'PUT /api/specialists/1/secrets': () => jsonResponse({ detail: 'O nome do segredo deve ter letras maiúsculas, números e _.' }, 422),
      })
      await wrapper.get('[data-test="secret-new-name"]').setValue('nome ruim')
      await wrapper.get('[data-test="secret-new-value"]').setValue('valor-que-nao-deve-aparecer')
      await wrapper.get('[data-test="secret-add"]').trigger('click')
      await flushPromises()
      expect(wrapper.get('[data-test="secret-error"]').text()).toBe('O nome do segredo deve ter letras maiúsculas, números e _.')
      expect(wrapper.html()).not.toContain('valor-que-nao-deve-aparecer')
    })
  })

  describe('MCPs', () => {
    it('sem execução ainda, explica quando aparece', async () => {
      const { wrapper } = await mountDetail()
      expect(wrapper.get('[data-test="mcp-empty"]').text()).toBe('Aparece depois da primeira execução.')
    })

    it('lista os servidores da última execução', async () => {
      const { wrapper } = await mountDetail(makeSpecialist({ last_mcp: [{ name: 'maestro', status: 'connected' }, { name: 'sentry', status: 'failed' }] }))
      expect(wrapper.findAll('[data-test="mcp-item"]').map((m) => m.text())).toEqual(['maestro connected', 'sentry failed'])
      expect(wrapper.find('[data-test="mcp-empty"]').exists()).toBe(false)
    })
  })

  describe('aprendizados', () => {
    it('mostra o contador n / 4.000 e acompanha a digitação', async () => {
      const { wrapper } = await mountDetail()
      expect(wrapper.get('[data-test="learnings-count"]').text()).toBe('16 / 4.000')
      await wrapper.get('[data-test="learnings-text"]').setValue('x'.repeat(1234))
      expect(wrapper.get('[data-test="learnings-count"]').text()).toBe('1.234 / 4.000')
    })

    it('passando do limite, avisa e não deixa salvar', async () => {
      const { wrapper } = await mountDetail()
      await wrapper.get('[data-test="learnings-text"]').setValue('x'.repeat(4001))
      expect(wrapper.get('[data-test="learnings-count"]').classes()).toContain('text-diff-del-fg')
      expect(wrapper.get('[data-test="learnings-save"]').attributes('disabled')).toBeDefined()
    })

    it('salva o texto e mantém o que foi digitado quando a API recusa', async () => {
      let fail = true
      const { wrapper, fetch } = await mountDetail(makeSpecialist(), {
        'PUT /api/specialists/1/learnings': () => (fail ? jsonResponse({ detail: 'Os aprendizados passam de 4.000 caracteres.' }, 422) : jsonResponse({ text: 'a' })),
      })
      await wrapper.get('[data-test="learnings-text"]').setValue('a')
      await wrapper.get('[data-test="learnings-save"]').trigger('click')
      await flushPromises()
      expect(wrapper.get('[data-test="learnings-error"]').text()).toBe('Os aprendizados passam de 4.000 caracteres.')
      expect(wrapper.get<HTMLTextAreaElement>('[data-test="learnings-text"]').element.value).toBe('a')
      fail = false
      await wrapper.get('[data-test="learnings-save"]').trigger('click')
      await flushPromises()
      expect(wrapper.find('[data-test="learnings-error"]').exists()).toBe(false)
      expect(bodies(fetch, 'PUT', '/api/specialists/1/learnings')).toHaveLength(2)
    })
  })

  describe('registro', () => {
    const item = (over: Partial<SpecialistItem> = {}): SpecialistItem => ({ key: 'SENTRY-1', status: 'pr_aberto', link: 'https://github.com/x/y/pull/1', note: 'Corrigido', created_at: 1_790_000_000, updated_at: 1_790_000_000, ...over })

    it('mostra a tabela e remove por linha', async () => {
      const { wrapper, fetch } = await mountDetail(makeSpecialist(), {
        'GET /api/specialists/1/items': () => jsonResponse([item(), item({ key: 'grupo/SENTRY 2', link: 'javascript:alert(1)', note: null })]),
        'DELETE /api/specialists/1/items/SENTRY-1': () => new Response(null, { status: 204 }),
        'DELETE /api/specialists/1/items/grupo/SENTRY%202': () => new Response(null, { status: 204 }),
      })
      const rows = wrapper.findAll('[data-test="item-row"]')
      expect(rows).toHaveLength(2)
      expect(rows[0]!.text()).toContain('SENTRY-1')
      expect(rows[0]!.text()).toContain('pr_aberto')
      expect(rows[0]!.text()).toContain('Corrigido')
      expect(rows[0]!.get('a').attributes('href')).toBe('https://github.com/x/y/pull/1')
      // só http e https viram link
      expect(rows[1]!.find('a').exists()).toBe(false)
      await rows[1]!.get('[data-test="item-remove"]').trigger('click')
      await flushPromises()
      expect(fetch.mock.calls.some(([u, init]) => u === '/api/specialists/1/items/grupo/SENTRY%202' && init?.method === 'DELETE')).toBe(true)
      expect(wrapper.findAll('[data-test="item-row"]')).toHaveLength(1)
    })

    it('sem itens, diz que está vazio', async () => {
      const { wrapper } = await mountDetail()
      expect(wrapper.find('[data-test="items-empty"]').exists()).toBe(true)
    })
  })

  describe('execuções', () => {
    it('lista data, gatilho, desfecho, motivo e link para a sessão', async () => {
      const { wrapper } = await mountDetail(makeSpecialist(), {
        'GET /api/specialists/1/runs?limit=50': () => jsonResponse([
          makeSpecialistRun({ id: 2, trigger: 'schedule', outcome: 'concluded', session_id: 's7' }),
          makeSpecialistRun({ id: 1, trigger: 'manual', outcome: 'failed', session_id: null, reason: 'A pasta do projeto não está disponível.' }),
        ]),
      })
      const rows = wrapper.findAll('[data-test="run-row"]')
      expect(rows).toHaveLength(2)
      expect(rows[0]!.text()).toContain('Horário')
      expect(rows[0]!.text()).toContain('Concluída')
      expect(rows[0]!.get('a').attributes('href')).toBe('/sessions/s7')
      expect(rows[1]!.text()).toContain('Manual')
      expect(rows[1]!.text()).toContain('Falhou')
      expect(rows[1]!.text()).toContain('A pasta do projeto não está disponível.')
      expect(rows[1]!.find('a').exists()).toBe(false)
    })
  })

  describe('modelo e raciocínio', () => {
    it('usa os mesmos menus da conversa e salva null para voltar ao padrão', async () => {
      const agent = makeSpecialist({ model: 'sonnet', effort: 'high' })
      const { wrapper, fetch } = await mountDetail(agent, {
        'GET /api/models': () => jsonResponse([
          { value: 'default', displayName: 'Padrão', description: '' },
          { value: 'sonnet', displayName: 'Sonnet', description: '', supportsEffort: true, supportedEffortLevels: ['low', 'high'] },
          { value: 'haiku', displayName: 'Haiku', description: '', supportsEffort: false },
        ]),
        'PATCH /api/specialists/1': () => jsonResponse(agent),
      })
      const [model, effort] = wrapper.findAllComponents(OptionMenu)
      expect(model!.props('text')).toBe('Sonnet')
      expect(model!.props('options').map((o: { label: string }) => o.label)).toEqual(['Padrão', 'Sonnet', 'Haiku'])
      expect(effort!.props('text')).toBe('Raciocínio alto')
      expect(effort!.props('options').map((o: { value: string }) => o.value)).toEqual(['', 'low', 'high'])
      effort!.vm.$emit('select', '')
      await flushPromises()
      expect(bodies(fetch, 'PATCH', '/api/specialists/1')).toEqual([{ effort: null }])
      // um modelo sem raciocínio zera o nível junto
      model!.vm.$emit('select', 'haiku')
      await flushPromises()
      expect(bodies(fetch, 'PATCH', '/api/specialists/1')[1]).toEqual({ model: 'haiku', effort: null })
    })
  })

  describe('mudança vinda de fora', () => {
    it('um specialist.changed reabre a skill, mas não atropela o que está sendo digitado', async () => {
      let disk = 'do disco'
      const { wrapper } = await mountDetail(makeSpecialist(), { 'GET /api/specialists/1/skill': () => jsonResponse({ text: disk }) })
      const area = wrapper.get<HTMLTextAreaElement>('[data-test="skill-text"]')
      expect(area.element.value).toBe('do disco')
      disk = 'mudou no disco'
      useSpecialistsStore().changes = { 1: 1 }
      await flushPromises()
      expect(area.element.value).toBe('mudou no disco')
      await area.setValue('meu texto')
      disk = 'mudou de novo'
      useSpecialistsStore().changes = { 1: 2 }
      await flushPromises()
      expect(area.element.value).toBe('meu texto')
    })
  })

  describe('excluir', () => {
    it('pede confirmação, exclui e volta para a lista', async () => {
      const { wrapper, fetch, router } = await mountDetail(makeSpecialist(), {
        'DELETE /api/specialists/1': () => new Response(null, { status: 204 }),
      })
      await wrapper.get('[data-test="agent-menu"]').trigger('click')
      await wrapper.get('[data-test="agent-delete"]').trigger('click')
      expect(fetch.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(false)
      await wrapper.get('[data-test="confirm-ok"]').trigger('click')
      await flushPromises()
      expect(fetch.mock.calls.some(([u, init]) => u === '/api/specialists/1' && init?.method === 'DELETE')).toBe(true)
      expect(router.currentRoute.value.fullPath).toBe('/agentes')
    })

    it('mostra o motivo quando a exclusão é recusada', async () => {
      const { wrapper, router } = await mountDetail(makeSpecialist(), {
        'DELETE /api/specialists/1': () => jsonResponse({ detail: 'O agente tem uma conversa com turno em andamento ou esperando você. Finalize-a antes de excluir o agente.' }, 409),
      })
      await wrapper.get('[data-test="agent-menu"]').trigger('click')
      await wrapper.get('[data-test="agent-delete"]').trigger('click')
      await wrapper.get('[data-test="confirm-ok"]').trigger('click')
      await flushPromises()
      expect(router.currentRoute.value.fullPath).toBe('/agentes/1')
      expect(wrapper.get('[data-test="action-error"]').text()).toContain('Finalize-a antes de excluir o agente.')
    })
  })

  it('salvar uma configuração com erro mostra a mensagem no topo', async () => {
    const { wrapper } = await mountDetail(makeSpecialist(), {
      'PATCH /api/specialists/1': () => jsonResponse({ detail: 'Projeto não encontrado.' }, 404),
    })
    await wrapper.get('[data-test="close-by-check"]').setValue(true)
    await flushPromises()
    expect(wrapper.get('[data-test="action-error"]').text()).toContain('Projeto não encontrado.')
  })
})
