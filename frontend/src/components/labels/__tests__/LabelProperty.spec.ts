import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import LabelProperty from '../LabelProperty.vue'
import { useLabelsStore } from '../../../stores/labels'
import { useSessionsStore } from '../../../stores/sessions'
import { jsonResponse, makeLabel, makeSession, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  useLabelsStore(pinia).labels = [makeLabel({ id: 1, slug: 'urgente' }), makeLabel({ id: 2, slug: 'backend' })]
})
afterEach(() => vi.unstubAllGlobals())

type Handlers = Record<string, (init: RequestInit | undefined) => Response | Promise<Response>>

function mountProperty(handlers: Handlers = {}, labelIds: number[] = []) {
  useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', label_ids: labelIds })])
  const fetchMock = routeFetch(handlers)
  vi.stubGlobal('fetch', fetchMock)
  const Host = { components: { LabelProperty }, template: '<dl><LabelProperty session-id="s1" /></dl>' }
  const wrapper = mount(Host, { global: { plugins: [pinia] }, attachTo: document.body })
  return { wrapper, fetchMock }
}

const bodies = (fetchMock: ReturnType<typeof routeFetch>, key: string) =>
  fetchMock.mock.calls
    .filter(([url, init]) => `${init?.method ?? 'GET'} ${url}` === key)
    .map(([, init]) => JSON.parse(String(init?.body)))

describe('propriedade Etiquetas', () => {
  it('mostra as etiquetas aplicadas e "Nenhuma" quando não há', async () => {
    const { wrapper } = mountProperty({}, [1])
    expect(wrapper.find('[data-test="prop-labels"]').text()).toContain('urgente')
    const empty = mountProperty()
    expect(empty.wrapper.find('[data-test="prop-labels"]').text()).toContain('Nenhuma')
  })

  it('marcar uma etiqueta envia a lista completa', async () => {
    const { wrapper, fetchMock } = mountProperty({
      'PUT /api/sessions/s1/labels': () => jsonResponse(makeSession({ session_id: 's1', label_ids: [1, 2] })),
    }, [1])
    await wrapper.find('[data-test="label-toggle"]').trigger('click')
    const options = wrapper.findAll('[data-test="label-option"]')
    expect(options.map((o) => o.attributes('data-slug'))).toEqual(['urgente', 'backend'])
    await options[1].find('input').setValue(true)
    await flushPromises()
    expect(bodies(fetchMock, 'PUT /api/sessions/s1/labels')).toEqual([{ label_ids: [1, 2] }])
  })

  it('desmarcar tira só aquela etiqueta', async () => {
    const { wrapper, fetchMock } = mountProperty({
      'PUT /api/sessions/s1/labels': () => jsonResponse(makeSession({ session_id: 's1', label_ids: [] })),
    }, [1])
    await wrapper.find('[data-test="label-toggle"]').trigger('click')
    await wrapper.findAll('[data-test="label-option"]')[0].find('input').setValue(false)
    await flushPromises()
    expect(bodies(fetchMock, 'PUT /api/sessions/s1/labels')).toEqual([{ label_ids: [] }])
  })

  it('cria uma etiqueta nova e já a aplica', async () => {
    const { wrapper, fetchMock } = mountProperty({
      'POST /api/labels': () => jsonResponse(makeLabel({ id: 3, slug: 'nova', color: '#00ff00' }), 201),
      'PUT /api/sessions/s1/labels': () => jsonResponse(makeSession({ session_id: 's1', label_ids: [1, 3] })),
    }, [1])
    await wrapper.find('[data-test="label-toggle"]').trigger('click')
    await wrapper.find('[data-test="label-new-slug"]').setValue('Nova')
    await wrapper.find('[data-test="label-new-color"]').setValue('#00ff00')
    await wrapper.find('[data-test="label-new-save"]').trigger('click')
    await flushPromises()
    expect(bodies(fetchMock, 'POST /api/labels')).toEqual([{ slug: 'Nova', color: '#00ff00' }])
    expect(bodies(fetchMock, 'PUT /api/sessions/s1/labels')).toEqual([{ label_ids: [1, 3] }])
    expect((wrapper.find('[data-test="label-new-slug"]').element as HTMLInputElement).value).toBe('')
  })

  it('mostra o erro do servidor e não aplica nada', async () => {
    const { wrapper, fetchMock } = mountProperty({
      'POST /api/labels': () => jsonResponse({ detail: 'Já existe uma etiqueta com esse slug.' }, 409),
    })
    await wrapper.find('[data-test="label-toggle"]').trigger('click')
    await wrapper.find('[data-test="label-new-slug"]').setValue('urgente')
    await wrapper.find('[data-test="label-new-save"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="label-error"]').text()).toBe('Já existe uma etiqueta com esse slug.')
    expect(bodies(fetchMock, 'PUT /api/sessions/s1/labels')).toEqual([])
  })

  it('se o PUT falhar, a caixa volta ao estado salvo e o erro aparece', async () => {
    const { wrapper } = mountProperty({
      'PUT /api/sessions/s1/labels': () => jsonResponse({ detail: 'Não foi possível salvar.' }, 500),
    }, [1])
    await wrapper.find('[data-test="label-toggle"]').trigger('click')
    const options = wrapper.findAll('[data-test="label-option"]')
    const marked = options[1].find('input')
    await marked.setValue(true)
    await flushPromises()
    expect((marked.element as HTMLInputElement).checked).toBe(false)
    const unmarked = options[0].find('input')
    await unmarked.setValue(false)
    await flushPromises()
    expect((unmarked.element as HTMLInputElement).checked).toBe(true)
    expect(wrapper.find('[data-test="label-error"]').text()).toBe('Não foi possível salvar.')
  })

  it('se criar der certo e aplicar falhar, limpa o campo e avisa que a etiqueta foi criada', async () => {
    const { wrapper } = mountProperty({
      'POST /api/labels': () => jsonResponse(makeLabel({ id: 3, slug: 'nova', color: '#00ff00' }), 201),
      'PUT /api/sessions/s1/labels': () => jsonResponse({ detail: 'Falhou.' }, 500),
    }, [1])
    await wrapper.find('[data-test="label-toggle"]').trigger('click')
    await wrapper.find('[data-test="label-new-slug"]').setValue('nova')
    await wrapper.find('[data-test="label-new-save"]').trigger('click')
    await flushPromises()
    expect((wrapper.find('[data-test="label-new-slug"]').element as HTMLInputElement).value).toBe('')
    expect(wrapper.findAll('[data-test="label-option"]').map((o) => o.attributes('data-slug'))).toContain('nova')
    expect(wrapper.find('[data-test="label-error"]').text()).toContain('foi criada')
    expect(wrapper.find('[data-test="label-error"]').text()).toContain('Marque-a na lista')
  })

  it('aria-controls só existe com o painel aberto', async () => {
    const { wrapper } = mountProperty()
    expect(wrapper.find('[data-test="label-toggle"]').attributes('aria-controls')).toBeUndefined()
    await wrapper.find('[data-test="label-toggle"]').trigger('click')
    expect(wrapper.find('[data-test="label-toggle"]').attributes('aria-controls')).toBe('labels-panel-s1')
  })

  it('não cria com o slug vazio', async () => {
    const { wrapper, fetchMock } = mountProperty()
    await wrapper.find('[data-test="label-toggle"]').trigger('click')
    expect(wrapper.find('[data-test="label-new-save"]').attributes('disabled')).toBeDefined()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
