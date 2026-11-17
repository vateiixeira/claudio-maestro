import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import LabelProperty from '../LabelProperty.vue'
import { LABEL_PALETTE } from '../../../labelColor'
import { useLabelsStore } from '../../../stores/labels'
import { useSessionsStore } from '../../../stores/sessions'
import { jsonResponse, makeLabel, makeSession, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  useLabelsStore(pinia).labels = [
    makeLabel({ id: 1, slug: 'urgente' }),
    makeLabel({ id: 2, slug: 'backend' }),
    makeLabel({ id: 3, slug: 'subir-e-avisar-cliente' }),
    makeLabel({ id: 4, slug: 'subir-e-avisar-suporte' }),
  ]
})
afterEach(() => vi.unstubAllGlobals())

type Handlers = Record<string, (init: RequestInit | undefined) => Response | Promise<Response>>

function mountProperty(handlers: Handlers = {}, labelIds: number[] = [], others: Array<number[]> = []) {
  useSessionsStore(pinia).setForProject(1, [
    makeSession({ session_id: 's1', label_ids: labelIds }),
    ...others.map((ids, index) => makeSession({ session_id: `o${index}`, label_ids: ids })),
  ])
  const fetchMock = routeFetch(handlers)
  vi.stubGlobal('fetch', fetchMock)
  const Host = { components: { LabelProperty }, template: '<dl><LabelProperty session-id="s1" /></dl>' }
  const wrapper = mount(Host, { global: { plugins: [pinia] }, attachTo: document.body })
  return { wrapper, fetchMock }
}

type Wrapper = ReturnType<typeof mountProperty>['wrapper']

const bodies = (fetchMock: ReturnType<typeof routeFetch>, key: string) =>
  fetchMock.mock.calls
    .filter(([url, init]) => `${init?.method ?? 'GET'} ${url}` === key)
    .map(([, init]) => JSON.parse(String(init?.body)))

const putOk = (label_ids: number[]) => ({
  'PUT /api/sessions/s1/labels': () => jsonResponse(makeSession({ session_id: 's1', label_ids })),
})

async function openPanel(wrapper: Wrapper) {
  await wrapper.find('[data-test="label-toggle"]').trigger('click')
  await flushPromises()
}
const search = (wrapper: Wrapper) => wrapper.find('[data-test="label-search"]')
const options = (wrapper: Wrapper) => wrapper.findAll('[data-test="label-option"]')
const slugs = (wrapper: Wrapper) => options(wrapper).map((o) => o.attributes('data-slug'))
const panel = (wrapper: Wrapper) => wrapper.find('[data-test="prop-labels"]')

describe('propriedade Etiquetas', () => {
  it('fechada, mostra as etiquetas aplicadas e "Nenhuma" quando não há', () => {
    const { wrapper } = mountProperty({}, [1])
    expect(panel(wrapper).text()).toContain('urgente')
    expect(wrapper.find('[data-test="label-search"]').exists()).toBe(false)
    const empty = mountProperty()
    expect(empty.wrapper.find('[data-test="prop-labels"]').text()).toContain('Nenhuma')
  })

  it('aberta, as etiquetas marcadas viram chips dentro do campo', async () => {
    const { wrapper } = mountProperty({}, [1, 2])
    await openPanel(wrapper)
    const chips = wrapper.findAll('[data-test="label-chip"]')
    expect(chips.map((c) => c.attributes('data-slug'))).toEqual(['urgente', 'backend'])
    expect(wrapper.findAll('[data-test="label-chip-remove"]')).toHaveLength(2)
  })

  it('o × de um chip desmarca só aquela etiqueta e devolve o foco ao campo', async () => {
    const { wrapper, fetchMock } = mountProperty(putOk([2]), [1, 2])
    await openPanel(wrapper)
    await wrapper.findAll('[data-test="label-chip-remove"]')[0].trigger('click')
    await flushPromises()
    expect(bodies(fetchMock, 'PUT /api/sessions/s1/labels')).toEqual([{ label_ids: [2] }])
    expect(wrapper.findAll('[data-test="label-chip"]').map((c) => c.attributes('data-slug'))).toEqual(['backend'])
    expect(document.activeElement).toBe(search(wrapper).element)
  })

  describe('clicar no campo', () => {
    // A browser moves the focus on mousedown unless it is cancelled; jsdom does not, so check the cancel.
    function mouseDown(target: Element): boolean {
      const event = new MouseEvent('mousedown', { bubbles: true, cancelable: true })
      target.dispatchEvent(event)
      return event.defaultPrevented
    }

    it('o mousedown na área vazia do campo não tira o foco do input', async () => {
      const { wrapper } = mountProperty({}, [1])
      await openPanel(wrapper)
      expect(mouseDown(wrapper.find('[data-test="label-field"]').element)).toBe(true)
    })

    it('o mousedown no corpo de um chip não tira o foco do input', async () => {
      const { wrapper } = mountProperty({}, [1])
      await openPanel(wrapper)
      expect(mouseDown(wrapper.find('[data-test="label-chip"]').element)).toBe(true)
      expect(mouseDown(wrapper.find('[data-test="label-chip"] span').element)).toBe(true)
    })

    it('o mousedown no próprio input segue o comportamento normal (posiciona o cursor)', async () => {
      const { wrapper } = mountProperty({}, [1])
      await openPanel(wrapper)
      expect(mouseDown(search(wrapper).element)).toBe(false)
    })

    it('clicar na área vazia ou num chip mantém o painel aberto com o foco no input', async () => {
      const { wrapper } = mountProperty({}, [1])
      await openPanel(wrapper)
      ;(wrapper.find('[data-test="label-toggle"]').element as HTMLElement).focus()
      await wrapper.find('[data-test="label-field"]').trigger('click')
      expect(search(wrapper).exists()).toBe(true)
      expect(document.activeElement).toBe(search(wrapper).element)
      ;(wrapper.find('[data-test="label-toggle"]').element as HTMLElement).focus()
      await wrapper.find('[data-test="label-chip"]').trigger('click')
      expect(search(wrapper).exists()).toBe(true)
      expect(document.activeElement).toBe(search(wrapper).element)
    })

    it('o × do chip continua desmarcando', async () => {
      const { wrapper, fetchMock } = mountProperty(putOk([]), [1])
      await openPanel(wrapper)
      expect(mouseDown(wrapper.find('[data-test="label-chip-remove"]').element)).toBe(true)
      await wrapper.find('[data-test="label-chip-remove"]').trigger('click')
      await flushPromises()
      expect(bodies(fetchMock, 'PUT /api/sessions/s1/labels')).toEqual([{ label_ids: [] }])
    })
  })

  it('o × tem nome acessível com a etiqueta', async () => {
    const { wrapper } = mountProperty({}, [1])
    await openPanel(wrapper)
    expect(wrapper.find('[data-test="label-chip-remove"]').attributes('aria-label')).toBe('Tirar a etiqueta urgente')
  })

  it('abrir põe o foco no campo, que é um combobox ligado à lista', async () => {
    const { wrapper } = mountProperty()
    await openPanel(wrapper)
    const input = search(wrapper)
    expect(document.activeElement).toBe(input.element)
    expect(input.attributes('role')).toBe('combobox')
    expect(input.attributes('aria-expanded')).toBe('true')
    const list = wrapper.find('[role="listbox"]')
    expect(list.exists()).toBe(true)
    expect(input.attributes('aria-controls')).toBe(list.attributes('id'))
    expect(options(wrapper).every((o) => o.attributes('role') === 'option')).toBe(true)
  })

  it('lista toda a etiqueta com a contagem de uso e a marca de selecionada', async () => {
    const { wrapper } = mountProperty({}, [1], [[1, 2], [2]])
    await openPanel(wrapper)
    const counts = Object.fromEntries(
      options(wrapper).map((o) => [o.attributes('data-slug'), o.find('[data-test="label-count"]').text()]),
    )
    expect(counts).toEqual({
      urgente: '2 conversas',
      backend: '2 conversas',
      'subir-e-avisar-cliente': 'sem uso',
      'subir-e-avisar-suporte': 'sem uso',
    })
    const selected = Object.fromEntries(options(wrapper).map((o) => [o.attributes('data-slug'), o.attributes('aria-selected')]))
    expect(selected.urgente).toBe('true')
    expect(selected.backend).toBe('false')
  })

  it('mostra "1 conversa" no singular', async () => {
    const { wrapper } = mountProperty({}, [1], [[2]])
    await openPanel(wrapper)
    expect(options(wrapper)[1].find('[data-test="label-count"]').text()).toBe('1 conversa')
  })

  it('digitar filtra pelo nome e destaca o trecho num <mark>', async () => {
    const { wrapper } = mountProperty()
    await openPanel(wrapper)
    await search(wrapper).setValue('avisar')
    expect(slugs(wrapper)).toEqual(['subir-e-avisar-cliente', 'subir-e-avisar-suporte'])
    const marks = options(wrapper)[0].findAll('mark')
    expect(marks).toHaveLength(1)
    expect(marks[0].text()).toBe('avisar')
  })

  it('o filtro ignora maiúsculas e espaços nas pontas', async () => {
    const { wrapper } = mountProperty()
    await openPanel(wrapper)
    await search(wrapper).setValue('  URGE ')
    expect(slugs(wrapper)).toEqual(['urgente'])
  })

  it('sem nenhuma opção que bata, só sobra a linha de criar', async () => {
    const { wrapper } = mountProperty()
    await openPanel(wrapper)
    await search(wrapper).setValue('xx')
    expect(options(wrapper)).toHaveLength(0)
    expect(wrapper.find('[data-test="label-new-save"]').exists()).toBe(true)
  })

  it('sem etiqueta com o nome exato, aparece "Criar etiqueta" com a paleta', async () => {
    const { wrapper } = mountProperty()
    await openPanel(wrapper)
    expect(wrapper.find('[data-test="label-new-save"]').exists()).toBe(false)
    await search(wrapper).setValue('avisar')
    const create = wrapper.find('[data-test="label-new-save"]')
    expect(create.exists()).toBe(true)
    expect(create.text()).toContain('Criar etiqueta')
    expect(wrapper.find('[data-test="label-new-color"]').findAll('[data-test="palette-color"]')).toHaveLength(7)
  })

  it('com o nome exato de uma etiqueta existente, não oferece criar', async () => {
    const { wrapper } = mountProperty()
    await openPanel(wrapper)
    await search(wrapper).setValue('Backend')
    expect(wrapper.find('[data-test="label-new-save"]').exists()).toBe(false)
    expect(slugs(wrapper)).toEqual(['backend'])
  })

  it('Enter cria com a primeira cor da paleta e já marca', async () => {
    const { wrapper, fetchMock } = mountProperty({
      'POST /api/labels': () => jsonResponse(makeLabel({ id: 9, slug: 'avisar', color: LABEL_PALETTE[0] }), 201),
      ...putOk([1, 9]),
    }, [1])
    await openPanel(wrapper)
    await search(wrapper).setValue('avisar')
    await search(wrapper).trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(bodies(fetchMock, 'POST /api/labels')).toEqual([{ slug: 'avisar', color: LABEL_PALETTE[0] }])
    expect(bodies(fetchMock, 'PUT /api/sessions/s1/labels')).toEqual([{ label_ids: [1, 9] }])
    expect((search(wrapper).element as HTMLInputElement).value).toBe('')
    expect(wrapper.findAll('[data-test="label-chip"]').map((c) => c.attributes('data-slug'))).toEqual(['urgente', 'avisar'])
  })

  it('cria com a cor escolhida na paleta', async () => {
    const { wrapper, fetchMock } = mountProperty({
      'POST /api/labels': () => jsonResponse(makeLabel({ id: 9, slug: 'avisar', color: LABEL_PALETTE[4] }), 201),
      ...putOk([9]),
    })
    await openPanel(wrapper)
    await search(wrapper).setValue('avisar')
    await wrapper.findAll('[data-test="palette-color"]')[4].trigger('click')
    await wrapper.find('[data-test="label-new-save"]').trigger('click')
    await flushPromises()
    expect(bodies(fetchMock, 'POST /api/labels')).toEqual([{ slug: 'avisar', color: LABEL_PALETTE[4] }])
  })

  it('depois de criar, a cor volta à primeira da paleta', async () => {
    const { wrapper } = mountProperty({
      'POST /api/labels': () => jsonResponse(makeLabel({ id: 9, slug: 'avisar' }), 201),
      ...putOk([9]),
    })
    await openPanel(wrapper)
    await search(wrapper).setValue('avisar')
    await wrapper.findAll('[data-test="palette-color"]')[4].trigger('click')
    await wrapper.find('[data-test="label-new-save"]').trigger('click')
    await flushPromises()
    await search(wrapper).setValue('outra')
    const pressed = wrapper.findAll('[data-test="palette-color"]').filter((b) => b.attributes('aria-pressed') === 'true')
    expect(pressed.map((b) => b.attributes('data-color'))).toEqual([LABEL_PALETTE[0]])
  })

  describe('teclado', () => {
    it('as setas mudam a opção em foco (aria-activedescendant)', async () => {
      const { wrapper } = mountProperty()
      await openPanel(wrapper)
      const input = search(wrapper)
      expect(input.attributes('aria-activedescendant')).toBeUndefined()
      await input.trigger('keydown', { key: 'ArrowDown' })
      expect(input.attributes('aria-activedescendant')).toBe(options(wrapper)[0].attributes('id'))
      await input.trigger('keydown', { key: 'ArrowDown' })
      expect(input.attributes('aria-activedescendant')).toBe(options(wrapper)[1].attributes('id'))
      await input.trigger('keydown', { key: 'ArrowUp' })
      expect(input.attributes('aria-activedescendant')).toBe(options(wrapper)[0].attributes('id'))
      expect(options(wrapper)[0].attributes('data-active')).toBe('true')
      expect(options(wrapper)[1].attributes('data-active')).toBeUndefined()
    })

    it('Enter marca a opção em foco e Enter de novo desmarca', async () => {
      const { wrapper, fetchMock } = mountProperty(putOk([2]))
      await openPanel(wrapper)
      const input = search(wrapper)
      await input.trigger('keydown', { key: 'ArrowDown' })
      await input.trigger('keydown', { key: 'ArrowDown' })
      await input.trigger('keydown', { key: 'Enter' })
      await flushPromises()
      expect(bodies(fetchMock, 'PUT /api/sessions/s1/labels')).toEqual([{ label_ids: [2] }])
      // The same option keeps the focus after saving.
      expect(input.attributes('aria-activedescendant')).toBe(options(wrapper)[1].attributes('id'))
    })

    it('Enter desmarca uma opção marcada', async () => {
      const { wrapper, fetchMock } = mountProperty(putOk([]), [1])
      await openPanel(wrapper)
      const input = search(wrapper)
      await input.trigger('keydown', { key: 'ArrowDown' })
      await input.trigger('keydown', { key: 'Enter' })
      await flushPromises()
      expect(bodies(fetchMock, 'PUT /api/sessions/s1/labels')).toEqual([{ label_ids: [] }])
    })

    it('Enter sem opção em foco e sem o que criar não faz nada', async () => {
      const { wrapper, fetchMock } = mountProperty()
      await openPanel(wrapper)
      await search(wrapper).trigger('keydown', { key: 'Enter' })
      await flushPromises()
      expect(fetchMock).not.toHaveBeenCalled()
    })

    it('com a opção em foco, Enter marca ela e não cria, mesmo com texto digitado', async () => {
      const { wrapper, fetchMock } = mountProperty(putOk([3]))
      await openPanel(wrapper)
      const input = search(wrapper)
      await input.setValue('avisar')
      await input.trigger('keydown', { key: 'ArrowDown' })
      await input.trigger('keydown', { key: 'Enter' })
      await flushPromises()
      expect(bodies(fetchMock, 'POST /api/labels')).toEqual([])
      expect(bodies(fetchMock, 'PUT /api/sessions/s1/labels')).toEqual([{ label_ids: [3] }])
    })

    it('a seta chega à linha "Criar etiqueta" e Enter nela cria', async () => {
      const { wrapper, fetchMock } = mountProperty({
        'POST /api/labels': () => jsonResponse(makeLabel({ id: 9, slug: 'zzz' }), 201),
        ...putOk([9]),
      })
      await openPanel(wrapper)
      const input = search(wrapper)
      await input.setValue('zzz')
      await input.trigger('keydown', { key: 'ArrowDown' })
      expect(input.attributes('aria-activedescendant')).toBe(wrapper.find('[data-test="label-new-save"]').attributes('id'))
      await input.trigger('keydown', { key: 'Enter' })
      await flushPromises()
      expect(bodies(fetchMock, 'POST /api/labels')).toHaveLength(1)
    })

    it('Esc fecha o painel e devolve o foco ao botão', async () => {
      const { wrapper } = mountProperty()
      await openPanel(wrapper)
      const outer = vi.fn()
      document.addEventListener('keydown', outer)
      await search(wrapper).trigger('keydown', { key: 'Escape' })
      document.removeEventListener('keydown', outer)
      expect(search(wrapper).exists()).toBe(false)
      expect(document.activeElement).toBe(wrapper.find('[data-test="label-toggle"]').element)
      expect(outer).not.toHaveBeenCalled()
    })

    it('mudar o texto zera a opção em foco', async () => {
      const { wrapper } = mountProperty()
      await openPanel(wrapper)
      const input = search(wrapper)
      await input.trigger('keydown', { key: 'ArrowDown' })
      await input.setValue('ur')
      expect(input.attributes('aria-activedescendant')).toBeUndefined()
    })
  })

  it('clicar numa opção marca; o painel continua aberto', async () => {
    const { wrapper, fetchMock } = mountProperty(putOk([1, 2]), [1])
    await openPanel(wrapper)
    await options(wrapper)[1].trigger('click')
    await flushPromises()
    expect(bodies(fetchMock, 'PUT /api/sessions/s1/labels')).toEqual([{ label_ids: [1, 2] }])
    expect(search(wrapper).exists()).toBe(true)
  })

  it('o foco saindo do conjunto fecha o painel, mas dentro dele não', async () => {
    const { wrapper } = mountProperty()
    await openPanel(wrapper)
    const palette = wrapper.find('[data-test="label-toggle"]').element
    await search(wrapper).trigger('focusout', { relatedTarget: palette })
    expect(search(wrapper).exists()).toBe(true)
    await search(wrapper).trigger('focusout', { relatedTarget: null })
    expect(search(wrapper).exists()).toBe(false)
  })

  it('se o PUT falhar, os chips voltam ao estado salvo e o erro aparece', async () => {
    const { wrapper } = mountProperty({
      'PUT /api/sessions/s1/labels': () => jsonResponse({ detail: 'Não foi possível salvar.' }, 500),
    }, [1])
    await openPanel(wrapper)
    await options(wrapper)[1].trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-test="label-chip"]').map((c) => c.attributes('data-slug'))).toEqual(['urgente'])
    expect(options(wrapper)[1].attributes('aria-selected')).toBe('false')
    expect(wrapper.find('[data-test="label-error"]').text()).toBe('Não foi possível salvar.')
    await wrapper.find('[data-test="label-chip-remove"]').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-test="label-chip"]')).toHaveLength(1)
  })

  it('mostra o erro do servidor ao criar e não aplica nada', async () => {
    const { wrapper, fetchMock } = mountProperty({
      'POST /api/labels': () => jsonResponse({ detail: 'Já existe uma etiqueta com esse slug.' }, 409),
    })
    await openPanel(wrapper)
    await search(wrapper).setValue('novo')
    await wrapper.find('[data-test="label-new-save"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="label-error"]').text()).toBe('Já existe uma etiqueta com esse slug.')
    expect(bodies(fetchMock, 'PUT /api/sessions/s1/labels')).toEqual([])
    expect((search(wrapper).element as HTMLInputElement).value).toBe('novo')
  })

  it('se criar der certo e aplicar falhar, limpa o campo e avisa que a etiqueta foi criada', async () => {
    const { wrapper } = mountProperty({
      'POST /api/labels': () => jsonResponse(makeLabel({ id: 9, slug: 'nova', color: '#00ff00' }), 201),
      'PUT /api/sessions/s1/labels': () => jsonResponse({ detail: 'Falhou.' }, 500),
    }, [1])
    await openPanel(wrapper)
    await search(wrapper).setValue('nova')
    await wrapper.find('[data-test="label-new-save"]').trigger('click')
    await flushPromises()
    expect((search(wrapper).element as HTMLInputElement).value).toBe('')
    expect(slugs(wrapper)).toContain('nova')
    expect(wrapper.find('[data-test="label-error"]').text()).toContain('foi criada')
    expect(wrapper.find('[data-test="label-error"]').text()).toContain('Marque-a na lista')
  })

  it('não apaga o que a pessoa digitou enquanto o pedido de criar rodava', async () => {
    let finishPost!: () => void
    const post = new Promise<Response>((resolve) => {
      finishPost = () => resolve(jsonResponse(makeLabel({ id: 9, slug: 'nova' }), 201))
    })
    const { wrapper } = mountProperty({ 'POST /api/labels': () => post, ...putOk([9]) })
    await openPanel(wrapper)
    await search(wrapper).setValue('nova')
    await wrapper.find('[data-test="label-new-save"]').trigger('click')
    await search(wrapper).setValue('proxima')
    finishPost()
    await flushPromises()
    expect((search(wrapper).element as HTMLInputElement).value).toBe('proxima')
  })

  it('aria-controls só existe com o painel aberto', async () => {
    const { wrapper } = mountProperty()
    expect(wrapper.find('[data-test="label-toggle"]').attributes('aria-controls')).toBeUndefined()
    await openPanel(wrapper)
    expect(wrapper.find('[data-test="label-toggle"]').attributes('aria-controls')).toBe('labels-panel-s1')
    expect(wrapper.find('#labels-panel-s1').exists()).toBe(true)
  })

  it('sem nenhuma etiqueta no catálogo, avisa e deixa criar a primeira', async () => {
    const { wrapper } = mountProperty()
    useLabelsStore(pinia).labels = []
    await openPanel(wrapper)
    expect(wrapper.text()).toContain('Nenhuma etiqueta criada ainda.')
    await search(wrapper).setValue('primeira')
    expect(wrapper.find('[data-test="label-new-save"]').exists()).toBe(true)
  })

  describe('durante um pedido em andamento', () => {
    function pendingPut() {
      let finish!: (label_ids: number[]) => void
      const response = new Promise<Response>((resolve) => {
        finish = (label_ids) => resolve(jsonResponse(makeSession({ session_id: 's1', label_ids })))
      })
      return { response, finish }
    }

    it('o campo não fica disabled (o foco não pode se perder) e o contêiner marca aria-busy', async () => {
      const put = pendingPut()
      const { wrapper } = mountProperty({ 'PUT /api/sessions/s1/labels': () => put.response }, [1])
      await openPanel(wrapper)
      expect(panel(wrapper).attributes('aria-busy')).toBeUndefined()
      await options(wrapper)[1].trigger('click')
      await flushPromises()
      expect(panel(wrapper).attributes('aria-busy')).toBe('true')
      expect(search(wrapper).attributes('disabled')).toBeUndefined()
      for (const remove of wrapper.findAll('[data-test="label-chip-remove"]')) {
        expect(remove.attributes('disabled')).toBeUndefined()
      }
      put.finish([1, 2])
      await flushPromises()
      expect(panel(wrapper).attributes('aria-busy')).toBeUndefined()
    })

    it('o campo mantém o foco durante e depois do pedido', async () => {
      const put = pendingPut()
      const { wrapper } = mountProperty({ 'PUT /api/sessions/s1/labels': () => put.response })
      await openPanel(wrapper)
      await search(wrapper).trigger('keydown', { key: 'ArrowDown' })
      await search(wrapper).trigger('keydown', { key: 'Enter' })
      await flushPromises()
      expect(document.activeElement).toBe(search(wrapper).element)
      put.finish([1])
      await flushPromises()
      expect(document.activeElement).toBe(search(wrapper).element)
    })

    it('uma segunda mudança durante o pedido é ignorada', async () => {
      const put = pendingPut()
      const { wrapper, fetchMock } = mountProperty({ 'PUT /api/sessions/s1/labels': () => put.response }, [1])
      await openPanel(wrapper)
      await options(wrapper)[1].trigger('click')
      await flushPromises()
      await options(wrapper)[0].trigger('click') // ignored: a request is still running
      await wrapper.find('[data-test="label-chip-remove"]').trigger('click') // ignored too
      await flushPromises()
      expect(bodies(fetchMock, 'PUT /api/sessions/s1/labels')).toEqual([{ label_ids: [1, 2] }])
      put.finish([1, 2])
      await flushPromises()
      expect(bodies(fetchMock, 'PUT /api/sessions/s1/labels')).toHaveLength(1)
      expect(panel(wrapper).attributes('aria-busy')).toBeUndefined()
    })

    it('"Criar etiqueta" usa aria-disabled durante o pedido e ignora um segundo envio', async () => {
      let finish!: () => void
      const post = new Promise<Response>((resolve) => {
        finish = () => resolve(jsonResponse(makeLabel({ id: 9, slug: 'nova' }), 201))
      })
      const { wrapper, fetchMock } = mountProperty({ 'POST /api/labels': () => post, ...putOk([9]) })
      await openPanel(wrapper)
      await search(wrapper).setValue('nova')
      const save = wrapper.find('[data-test="label-new-save"]')
      expect(save.attributes('aria-disabled')).toBeUndefined()
      await save.trigger('click')
      await flushPromises()
      expect(save.attributes('disabled')).toBeUndefined()
      expect(save.attributes('aria-disabled')).toBe('true')
      expect(panel(wrapper).attributes('aria-busy')).toBe('true')
      await search(wrapper).trigger('keydown', { key: 'Enter' }) // Enter in the field: ignored too
      await flushPromises()
      expect(bodies(fetchMock, 'POST /api/labels')).toHaveLength(1)
      finish()
      await flushPromises()
      expect(bodies(fetchMock, 'POST /api/labels')).toHaveLength(1)
      expect(panel(wrapper).attributes('aria-busy')).toBeUndefined()
    })
  })
})
