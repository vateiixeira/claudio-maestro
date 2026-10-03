import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import PreferencesView from '../PreferencesView.vue'
import { createAppRouter } from '../../router'
import { jsonResponse, routeFetch } from '../../test/factories'
import { useLayoutStore } from '../../stores/layout'

enableAutoUnmount(afterEach)

let pinia: Pinia
let saved: unknown[]

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  saved = []
})
afterEach(() => vi.unstubAllGlobals())

function stub(state: unknown, put?: (body: unknown) => Response) {
  const fetchMock = routeFetch({
    'GET /api/state': () => jsonResponse(state),
    'PUT /api/state/preferences': (init) => {
      const body = JSON.parse(String(init?.body))
      saved.push(body)
      return put ? put(body) : jsonResponse(body)
    },
    'GET /api/projects': () => jsonResponse([]),
    'GET /api/models': () => jsonResponse([]),
    'GET /api/digest/config': () => jsonResponse({
      config: { enabled: false, model: 'sonnet', effort: 'medium', extra_instructions: '', interval_minutes: 10, min_new_messages: 10, open_turn_minutes: 30, window_days: 3 },
      status: { enabled: false, running: false, next_run_at: null, paused_until: null },
    }),
    'GET /api/digest/runs': () => jsonResponse([]),
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function mountView() {
  const router = createAppRouter(createMemoryHistory())
  await router.push('/preferencias')
  const wrapper = mount(PreferencesView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return wrapper
}

const editor = (w: Awaited<ReturnType<typeof mountView>>) => w.find<HTMLInputElement>('#pref-editor')
const days = (w: Awaited<ReturnType<typeof mountView>>) => w.find<HTMLInputElement>('#pref-days')

describe('tela de preferências', () => {
  it('a rota existe', () => {
    const router = createAppRouter(createMemoryHistory())
    expect(router.resolve('/preferencias').name).toBe('preferences')
  })

  it('abre na aba Geral e troca para a do agente pela URL', async () => {
    stub({ preferences: {} })
    const w = await mountView()
    expect(w.find('[data-test="tab-general"]').attributes('aria-selected')).toBe('true')
    expect(w.find('#pref-editor').exists()).toBe(true)
    await w.find('[data-test="tab-agent"]').trigger('click')
    await flushPromises()
    expect(w.find('#digest-enabled').exists()).toBe(true)
    expect(w.find('#pref-editor').exists()).toBe(false)
  })

  it('a aba Notificações abre pela URL e tem a ordem Geral, Agente, Notificações nas setas', async () => {
    stub({ preferences: {} })
    vi.stubGlobal('Notification', undefined)
    const router = createAppRouter(createMemoryHistory())
    await router.push('/preferencias')
    const w = mount(PreferencesView, { global: { plugins: [pinia, router] } })
    await flushPromises()
    expect(w.find('[data-test="tab-notifications"]').text()).toBe('Notificações')
    await w.find('[data-test="tab-notifications"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.aba).toBe('notificacoes')
    expect(w.find('[data-test="tab-notifications"]').attributes('aria-selected')).toBe('true')
    expect(w.find('[data-test="notif-unsupported"]').exists()).toBe(true)
    expect(w.find('#pref-editor').exists()).toBe(false)
    await w.find('[role="tablist"]').trigger('keydown', { key: 'ArrowRight' })
    await flushPromises()
    expect(w.find('[data-test="tab-general"]').attributes('aria-selected')).toBe('true')
    await w.find('[role="tablist"]').trigger('keydown', { key: 'ArrowLeft' })
    await flushPromises()
    expect(router.currentRoute.value.query.aba).toBe('notificacoes')
  })

  it('a aba ativa vem da URL e as setas trocam de aba', async () => {
    stub({ preferences: {} })
    const router = createAppRouter(createMemoryHistory())
    await router.push('/preferencias?aba=agente')
    const w = mount(PreferencesView, { global: { plugins: [pinia, router] } })
    await flushPromises()
    expect(w.find('[data-test="tab-agent"]').attributes('aria-selected')).toBe('true')
    expect(w.find('[data-test="tab-general"]').attributes('tabindex')).toBe('-1')
    await w.find('[role="tablist"]').trigger('keydown', { key: 'ArrowLeft' })
    await flushPromises()
    expect(router.currentRoute.value.query.aba).toBeUndefined()
    expect(w.find('#pref-editor').exists()).toBe(true)
  })

  it('mostra os valores salvos e explica como o comando é usado', async () => {
    stub({ preferences: { editor_command: ['code', '--reuse-window'], finished_after_days: 7 } })
    const w = await mountView()
    expect(editor(w).element.value).toBe('code --reuse-window')
    expect(days(w).element.value).toBe('7')
    expect(w.find('[data-test="editor-help"]').text()).toContain('caminho')
    expect(w.find('[data-test="editor-help"]').text()).toContain('final')
  })

  it('sem preferências salvas usa o comando padrão como dica e 3 dias', async () => {
    stub({})
    const w = await mountView()
    expect(editor(w).element.value).toBe('')
    expect(editor(w).attributes('placeholder')).toBe('code')
    expect(days(w).element.value).toBe('3')
  })

  it('salva preservando as outras chaves, confirma e atualiza o layout sem recarregar', async () => {
    stub({ layout: { columns: [] }, preferences: { editor_command: ['code'], finished_after_days: 3, tema: 'escuro' } })
    const w = await mountView()
    await editor(w).setValue('"/opt/meu editor/bin" --wait')
    await days(w).setValue('10')
    await w.find('form').trigger('submit')
    await flushPromises()

    expect(saved).toEqual([{ editor_command: ['/opt/meu editor/bin', '--wait'], finished_after_days: 10, tema: 'escuro', new_session_model: null, new_session_effort: null, new_session_mode: null }])
    expect(w.find('[data-test="saved"]').text()).toContain('Preferências salvas')
    expect(w.find('[role="alert"]').exists()).toBe(false)
    expect(useLayoutStore(pinia).finishedAfterDays).toBe(10)
  })

  it('campo do editor vazio remove a chave e volta ao padrão', async () => {
    stub({ preferences: { editor_command: ['subl'], finished_after_days: 3, outro: 1 } })
    const w = await mountView()
    await editor(w).setValue('')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(saved).toEqual([{ finished_after_days: 3, outro: 1, new_session_model: null, new_session_effort: null, new_session_mode: null }])
  })

  it('mostra o erro do backend e não confirma nem muda o layout', async () => {
    stub({}, () => jsonResponse({ detail: 'O comando do editor precisa ser uma lista de textos não vazios.' }, 400))
    const w = await mountView()
    await days(w).setValue('9')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(w.find('[role="alert"]').text()).toContain('O comando do editor precisa ser uma lista de textos não vazios.')
    expect(w.find('[data-test="saved"]').exists()).toBe(false)
    expect(useLayoutStore(pinia).finishedAfterDays).toBe(3)
  })

  it.each(['0', '366', '2.5', ''])('dias inválidos (%s) não são enviados', async (value) => {
    stub({})
    const w = await mountView()
    await days(w).setValue(value)
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(saved).toEqual([])
    expect(w.find('[role="alert"]').text()).toContain('entre 1 e 365')
  })

  it('aspas sem fechar no comando mostram erro e não enviam', async () => {
    stub({})
    const w = await mountView()
    await editor(w).setValue('code "abc')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(saved).toEqual([])
    expect(w.find('[role="alert"]').text()).toContain('Aspas sem fechar.')
  })

  it.each(['code ""', "''", 'code "" --wait'])('argumento vazio (%s) mostra mensagem própria e não envia', async (value) => {
    stub({})
    const w = await mountView()
    await editor(w).setValue(value)
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(saved).toEqual([])
    expect(w.find('[role="alert"]').text()).toContain('argumento vazio')
  })

  it('falha ao ler as preferências mostra o erro e permite tentar de novo', async () => {
    let ok = false
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/state': () => (ok ? jsonResponse({ preferences: { finished_after_days: 4 } }) : jsonResponse({ detail: 'Banco indisponível.' }, 500)),
    }))
    const w = await mountView()
    expect(w.find('[role="alert"]').text()).toContain('Banco indisponível.')
    expect(w.find('[data-test="save"]').attributes('disabled')).toBeDefined()
    ok = true
    await w.find('[data-test="retry"]').trigger('click')
    await flushPromises()
    expect(days(w).element.value).toBe('4')
    expect(w.find('[role="alert"]').exists()).toBe(false)
  })

  it('lê as preferências de novo na hora de salvar, para não apagar chaves de outra aba', async () => {
    let calls = 0
    vi.stubGlobal('fetch', routeFetch({
      'GET /api/state': () => jsonResponse({ preferences: calls++ === 0 ? { finished_after_days: 3 } : { finished_after_days: 3, nova: true } }),
      'PUT /api/state/preferences': (init) => { saved.push(JSON.parse(String(init?.body))); return jsonResponse({}) },
      'GET /api/projects': () => jsonResponse([]),
      'GET /api/models': () => jsonResponse([]),
    }))
    const w = await mountView()
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(saved).toEqual([{ finished_after_days: 3, nova: true, new_session_model: null, new_session_effort: null, new_session_mode: null }])
  })
})
