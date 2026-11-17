import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import LabelPreferences from '../LabelPreferences.vue'
import { useLabelsStore } from '../../../stores/labels'
import { useSessionsStore } from '../../../stores/sessions'
import { jsonResponse, makeLabel, makeSession, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  // Catalog order: backend (1 use), urgente (2 uses), zeta and omega (no use).
  useLabelsStore(pinia).labels = [
    makeLabel({ id: 2, slug: 'backend', color: '#a9dc76' }),
    makeLabel({ id: 1, slug: 'urgente', color: '#ef4444' }),
    makeLabel({ id: 3, slug: 'zeta', color: '#ffd866' }),
    makeLabel({ id: 4, slug: 'omega', color: '#ab9df2' }),
  ]
  useSessionsStore(pinia).setForProject(1, [
    makeSession({ session_id: 's1', label_ids: [1] }),
    makeSession({ session_id: 's2', label_ids: [1, 2] }),
  ])
})
afterEach(() => vi.unstubAllGlobals())

const mountPrefs = (handlers = {}) => {
  const fetchMock = routeFetch(handlers)
  vi.stubGlobal('fetch', fetchMock)
  return { wrapper: mount(LabelPreferences, { global: { plugins: [pinia] } }), fetchMock }
}

const rowOf = (wrapper: VueWrapper, slug: string) => wrapper.find(`[data-test="label-row"][data-slug="${slug}"]`)
const calls = (fetchMock: ReturnType<typeof routeFetch>, key: string) =>
  fetchMock.mock.calls.filter(([url, init]) => `${init?.method} ${url}` === key)
const bodyOf = (call: unknown[]) => JSON.parse(String((call[1] as RequestInit).body))

describe('preferências de etiquetas', () => {
  it('ordena por uso, do maior para o menor, e deixa as sem uso para o fim', () => {
    const { wrapper } = mountPrefs()
    expect(wrapper.findAll('[data-test="label-row"]').map((r) => r.attributes('data-slug'))).toEqual(['urgente', 'backend', 'zeta', 'omega'])
    expect(rowOf(wrapper, 'urgente').text()).toContain('2 conversas')
    expect(rowOf(wrapper, 'backend').text()).toContain('1 conversa')
    expect(rowOf(wrapper, 'zeta').text()).toContain('sem uso')
  })

  it('o empate de uso segue a ordem do catálogo', () => {
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', label_ids: [1, 2] })])
    const { wrapper } = mountPrefs()
    expect(wrapper.findAll('[data-test="label-row"]').map((r) => r.attributes('data-slug'))).toEqual(['backend', 'urgente', 'zeta', 'omega'])
  })

  describe('renomear', () => {
    const input = (wrapper: VueWrapper, slug: string) => rowOf(wrapper, slug).find('[data-test="label-edit-slug"]')

    it('sair do campo salva o novo nome, uma vez', async () => {
      const { wrapper, fetchMock } = mountPrefs({
        'PATCH /api/labels/1': () => jsonResponse(makeLabel({ id: 1, slug: 'critico', color: '#ef4444' })),
      })
      await input(wrapper, 'urgente').setValue('critico')
      await input(wrapper, 'urgente').trigger('blur')
      await flushPromises()
      const patches = calls(fetchMock, 'PATCH /api/labels/1')
      expect(patches).toHaveLength(1)
      expect(bodyOf(patches[0]!)).toEqual({ slug: 'critico' })
      expect(useLabelsStore(pinia).byId(1)?.slug).toBe('critico')
    })

    it('Enter salva, e o blur que vem depois não salva de novo', async () => {
      const { wrapper, fetchMock } = mountPrefs({
        'PATCH /api/labels/1': () => jsonResponse(makeLabel({ id: 1, slug: 'critico', color: '#ef4444' })),
      })
      await input(wrapper, 'urgente').setValue('critico')
      await input(wrapper, 'urgente').trigger('keydown', { key: 'Enter' })
      await input(wrapper, 'urgente').trigger('blur')
      await flushPromises()
      expect(calls(fetchMock, 'PATCH /api/labels/1')).toHaveLength(1)
    })

    it('sem mudança não chama a API', async () => {
      const { wrapper, fetchMock } = mountPrefs()
      await input(wrapper, 'urgente').trigger('blur')
      await input(wrapper, 'urgente').trigger('keydown', { key: 'Enter' })
      // Same name, only spaces and capitals around it.
      await input(wrapper, 'urgente').setValue('  Urgente ')
      await input(wrapper, 'urgente').trigger('blur')
      await flushPromises()
      expect(calls(fetchMock, 'PATCH /api/labels/1')).toHaveLength(0)
    })

    it('Esc volta ao nome salvo sem salvar', async () => {
      const { wrapper, fetchMock } = mountPrefs()
      await input(wrapper, 'urgente').setValue('outro')
      await input(wrapper, 'urgente').trigger('keydown', { key: 'Escape' })
      expect((input(wrapper, 'urgente').element as HTMLInputElement).value).toBe('urgente')
      await input(wrapper, 'urgente').trigger('blur')
      await flushPromises()
      expect(calls(fetchMock, 'PATCH /api/labels/1')).toHaveLength(0)
    })

    it('mostra o erro na própria linha e o campo volta ao nome salvo', async () => {
      const { wrapper } = mountPrefs({
        'PATCH /api/labels/2': () => jsonResponse({ detail: 'Já existe uma etiqueta com esse slug.' }, 409),
      })
      await input(wrapper, 'backend').setValue('urgente')
      await input(wrapper, 'backend').trigger('blur')
      await flushPromises()
      expect(rowOf(wrapper, 'backend').find('[data-test="label-error"]').text()).toBe('Já existe uma etiqueta com esse slug.')
      expect((input(wrapper, 'backend').element as HTMLInputElement).value).toBe('backend')
      expect(rowOf(wrapper, 'urgente').find('[data-test="label-error"]').exists()).toBe(false)
    })

    it('o erro some quando a pessoa volta a digitar', async () => {
      const { wrapper } = mountPrefs({
        'PATCH /api/labels/2': () => jsonResponse({ detail: 'Já existe uma etiqueta com esse slug.' }, 409),
      })
      await input(wrapper, 'backend').setValue('urgente')
      await input(wrapper, 'backend').trigger('blur')
      await flushPromises()
      await input(wrapper, 'backend').setValue('api')
      expect(rowOf(wrapper, 'backend').find('[data-test="label-error"]').exists()).toBe(false)
    })

    it('nome vazio não vai para a API e volta ao nome salvo', async () => {
      const { wrapper, fetchMock } = mountPrefs()
      await input(wrapper, 'backend').setValue('   ')
      await input(wrapper, 'backend').trigger('blur')
      await flushPromises()
      expect(calls(fetchMock, 'PATCH /api/labels/2')).toHaveLength(0)
      expect((input(wrapper, 'backend').element as HTMLInputElement).value).toBe('backend')
    })

    it('o rascunho acompanha o catálogo recarregado, menos quando há edição pendente', async () => {
      const { wrapper } = mountPrefs()
      const slugOf = (slug: string) => (input(wrapper, slug).element as HTMLInputElement).value
      await input(wrapper, 'backend').setValue('meu-rascunho')
      // Another tab renames both labels.
      useLabelsStore(pinia).labels = [
        makeLabel({ id: 2, slug: 'novo-backend', color: '#a9dc76' }),
        makeLabel({ id: 1, slug: 'outro-nome', color: '#ef4444' }),
      ]
      await flushPromises()
      expect(slugOf('outro-nome')).toBe('outro-nome')
      expect(slugOf('novo-backend')).toBe('meu-rascunho')
    })
  })

  describe('cor', () => {
    it('escolher uma cor na paleta salva na hora', async () => {
      const { wrapper, fetchMock } = mountPrefs({
        'PATCH /api/labels/1': () => jsonResponse(makeLabel({ id: 1, slug: 'urgente', color: '#78dce8' })),
      })
      const row = rowOf(wrapper, 'urgente')
      expect(row.find('[data-test="palette-color"]').exists()).toBe(false)
      await row.find('[data-test="label-edit-color"]').trigger('click')
      await row.find('[data-test="palette-color"][data-color="#78dce8"]').trigger('click')
      await flushPromises()
      const patches = calls(fetchMock, 'PATCH /api/labels/1')
      expect(patches).toHaveLength(1)
      expect(bodyOf(patches[0]!)).toEqual({ color: '#78dce8' })
      expect(useLabelsStore(pinia).byId(1)?.color).toBe('#78dce8')
      // The palette closes after the pick.
      expect(rowOf(wrapper, 'urgente').find('[data-test="palette-color"]').exists()).toBe(false)
    })

    it('o botão da cor diz de qual etiqueta é e abre e fecha a paleta', async () => {
      const { wrapper } = mountPrefs()
      const button = rowOf(wrapper, 'urgente').find('[data-test="label-edit-color"]')
      expect(button.attributes('aria-label')).toBe('Trocar a cor de urgente')
      expect(button.attributes('aria-expanded')).toBe('false')
      await button.trigger('click')
      expect(button.attributes('aria-expanded')).toBe('true')
      await button.trigger('click')
      expect(rowOf(wrapper, 'urgente').find('[data-test="palette-color"]').exists()).toBe(false)
    })

    it('erro ao trocar a cor aparece na linha e a cor salva continua', async () => {
      const { wrapper } = mountPrefs({
        'PATCH /api/labels/1': () => jsonResponse({ detail: 'Falhou.' }, 500),
      })
      const row = rowOf(wrapper, 'urgente')
      await row.find('[data-test="label-edit-color"]').trigger('click')
      await row.find('[data-test="palette-color"][data-color="#78dce8"]').trigger('click')
      await flushPromises()
      expect(rowOf(wrapper, 'urgente').find('[data-test="label-error"]').text()).toBe('Falhou.')
      expect(useLabelsStore(pinia).byId(1)?.color).toBe('#ef4444')
    })
  })

  describe('várias edições na mesma linha', () => {
    // A PATCH that stays pending until `release` is called, then the next ones answer at once.
    function slowPatch(id: number, answers: Array<Record<string, unknown>>) {
      const releases: Array<() => void> = []
      let n = 0
      const handler = () => {
        const answer = jsonResponse(makeLabel({ id, ...answers[n++] }))
        if (n > 1) return answer
        return new Promise<Response>((resolve) => releases.push(() => resolve(answer)))
      }
      return { handler, release: () => releases.shift()?.() }
    }
    const input = (wrapper: VueWrapper, slug: string) => rowOf(wrapper, slug).find('[data-test="label-edit-slug"]')

    it('renomear com a cor ainda salvando espera e envia o nome depois', async () => {
      const slow = slowPatch(1, [{ slug: 'urgente', color: '#78dce8' }, { slug: 'critico', color: '#78dce8' }])
      const { wrapper, fetchMock } = mountPrefs({ 'PATCH /api/labels/1': slow.handler })
      const row = rowOf(wrapper, 'urgente')
      await row.find('[data-test="label-edit-color"]').trigger('click')
      await row.find('[data-test="palette-color"][data-color="#78dce8"]').trigger('click')
      await input(wrapper, 'urgente').setValue('critico')
      await input(wrapper, 'urgente').trigger('blur')
      expect(calls(fetchMock, 'PATCH /api/labels/1')).toHaveLength(1)
      // The typed name is still there while the first save is pending.
      expect((input(wrapper, 'urgente').element as HTMLInputElement).value).toBe('critico')
      slow.release()
      await flushPromises()
      const patches = calls(fetchMock, 'PATCH /api/labels/1')
      expect(patches).toHaveLength(2)
      expect(bodyOf(patches[0]!)).toEqual({ color: '#78dce8' })
      expect(bodyOf(patches[1]!)).toEqual({ slug: 'critico' })
      expect(useLabelsStore(pinia).byId(1)).toMatchObject({ slug: 'critico', color: '#78dce8' })
      expect(rowOf(wrapper, 'critico').find('[data-test="label-error"]').exists()).toBe(false)
    })

    it('trocar a cor com o nome ainda salvando espera e envia a cor depois', async () => {
      const slow = slowPatch(1, [{ slug: 'critico', color: '#ef4444' }, { slug: 'critico', color: '#78dce8' }])
      const { wrapper, fetchMock } = mountPrefs({ 'PATCH /api/labels/1': slow.handler })
      await input(wrapper, 'urgente').setValue('critico')
      await input(wrapper, 'urgente').trigger('keydown', { key: 'Enter' })
      const row = rowOf(wrapper, 'urgente')
      await row.find('[data-test="label-edit-color"]').trigger('click')
      await row.find('[data-test="palette-color"][data-color="#78dce8"]').trigger('click')
      expect(calls(fetchMock, 'PATCH /api/labels/1')).toHaveLength(1)
      slow.release()
      await flushPromises()
      const patches = calls(fetchMock, 'PATCH /api/labels/1')
      expect(patches).toHaveLength(2)
      expect(bodyOf(patches[1]!)).toEqual({ color: '#78dce8' })
      expect(useLabelsStore(pinia).byId(1)).toMatchObject({ slug: 'critico', color: '#78dce8' })
    })

    it('o que foi digitado durante o salvamento não se perde nem volta ao nome antigo', async () => {
      const slow = slowPatch(1, [{ slug: 'critico' }, { slug: 'grave' }])
      const { wrapper, fetchMock } = mountPrefs({ 'PATCH /api/labels/1': slow.handler })
      await input(wrapper, 'urgente').setValue('critico')
      await input(wrapper, 'urgente').trigger('blur')
      await input(wrapper, 'urgente').setValue('grave')
      slow.release()
      await flushPromises()
      // Typed again but not committed yet: the field keeps it.
      expect((input(wrapper, 'critico').element as HTMLInputElement).value).toBe('grave')
      expect(calls(fetchMock, 'PATCH /api/labels/1')).toHaveLength(1)
      await input(wrapper, 'critico').trigger('blur')
      await flushPromises()
      const patches = calls(fetchMock, 'PATCH /api/labels/1')
      expect(patches).toHaveLength(2)
      expect(bodyOf(patches[1]!)).toEqual({ slug: 'grave' })
      expect(useLabelsStore(pinia).byId(1)?.slug).toBe('grave')
    })

    it('Esc durante o salvamento tira da fila o nome ainda não enviado', async () => {
      const slow = slowPatch(1, [{ slug: 'urgente', color: '#78dce8' }])
      const { wrapper, fetchMock } = mountPrefs({ 'PATCH /api/labels/1': slow.handler })
      const row = rowOf(wrapper, 'urgente')
      await row.find('[data-test="label-edit-color"]').trigger('click')
      await row.find('[data-test="palette-color"][data-color="#78dce8"]').trigger('click')
      await input(wrapper, 'urgente').setValue('critico')
      await input(wrapper, 'urgente').trigger('blur')
      await input(wrapper, 'urgente').trigger('keydown', { key: 'Escape' })
      slow.release()
      await flushPromises()
      expect(calls(fetchMock, 'PATCH /api/labels/1')).toHaveLength(1)
      expect((input(wrapper, 'urgente').element as HTMLInputElement).value).toBe('urgente')
    })

    describe('cor personalizada', () => {
      beforeEach(() => vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] }))
      afterEach(() => vi.useRealTimers())

      it('arrastar o seletor não fecha a paleta e salva só a cor final, depois de uma pausa', async () => {
        const { wrapper, fetchMock } = mountPrefs({
          'PATCH /api/labels/1': () => jsonResponse(makeLabel({ id: 1, slug: 'urgente', color: '#123456' })),
        })
        const row = rowOf(wrapper, 'urgente')
        await row.find('[data-test="label-edit-color"]').trigger('click')
        const picker = row.find('input[type="color"]')
        await picker.setValue('#111111')
        await picker.setValue('#112233')
        await picker.setValue('#123456')
        expect(rowOf(wrapper, 'urgente').find('[data-test="palette-color"]').exists()).toBe(true)
        expect(calls(fetchMock, 'PATCH /api/labels/1')).toHaveLength(0)
        await vi.advanceTimersByTimeAsync(400)
        const patches = calls(fetchMock, 'PATCH /api/labels/1')
        expect(patches).toHaveLength(1)
        expect(bodyOf(patches[0]!)).toEqual({ color: '#123456' })
        expect(useLabelsStore(pinia).byId(1)?.color).toBe('#123456')
        expect(rowOf(wrapper, 'urgente').find('[data-test="palette-color"]').exists()).toBe(true)
      })

      it('uma cor fixa escolhida durante a pausa vale no lugar da personalizada', async () => {
        const { wrapper, fetchMock } = mountPrefs({
          'PATCH /api/labels/1': () => jsonResponse(makeLabel({ id: 1, slug: 'urgente', color: '#78dce8' })),
        })
        const row = rowOf(wrapper, 'urgente')
        await row.find('[data-test="label-edit-color"]').trigger('click')
        await row.find('input[type="color"]').setValue('#123456')
        await row.find('[data-test="palette-color"][data-color="#78dce8"]').trigger('click')
        await vi.advanceTimersByTimeAsync(400)
        const patches = calls(fetchMock, 'PATCH /api/labels/1')
        expect(patches).toHaveLength(1)
        expect(bodyOf(patches[0]!)).toEqual({ color: '#78dce8' })
      })

      it('desmontar com a cor ainda na pausa salva ao sair', async () => {
        const { wrapper, fetchMock } = mountPrefs({
          'PATCH /api/labels/1': () => jsonResponse(makeLabel({ id: 1, slug: 'urgente', color: '#123456' })),
        })
        const row = rowOf(wrapper, 'urgente')
        await row.find('[data-test="label-edit-color"]').trigger('click')
        await row.find('input[type="color"]').setValue('#123456')
        wrapper.unmount()
        await vi.advanceTimersByTimeAsync(0)
        expect(calls(fetchMock, 'PATCH /api/labels/1')).toHaveLength(1)
      })
    })
  })

  describe('apagar uma etiqueta', () => {
    it('pede confirmação, diz quantas conversas perdem a etiqueta e só então apaga', async () => {
      const { wrapper, fetchMock } = mountPrefs({ 'DELETE /api/labels/1': () => new Response(null, { status: 204 }) })
      const row = rowOf(wrapper, 'urgente')
      expect(row.text()).not.toContain('tira a etiqueta')
      await row.find('[data-test="label-delete"]').trigger('click')
      expect(row.text()).toContain('tira a etiqueta de 2 conversas')
      expect(calls(fetchMock, 'DELETE /api/labels/1')).toHaveLength(0)
      await row.find('[data-test="label-delete-confirm"]').trigger('click')
      await flushPromises()
      expect(calls(fetchMock, 'DELETE /api/labels/1')).toHaveLength(1)
      expect(useLabelsStore(pinia).byId(1)).toBeUndefined()
    })

    it('uma etiqueta sem uso não diz "de sem uso"', async () => {
      const { wrapper } = mountPrefs()
      await rowOf(wrapper, 'zeta').find('[data-test="label-delete"]').trigger('click')
      expect(rowOf(wrapper, 'zeta').text()).not.toContain('de sem uso')
      expect(rowOf(wrapper, 'zeta').find('[data-test="label-delete-confirm"]').exists()).toBe(true)
    })

    it('uma etiqueta apagada em outra aba some da lista e fecha a confirmação', async () => {
      const { wrapper } = mountPrefs()
      await rowOf(wrapper, 'urgente').find('[data-test="label-delete"]').trigger('click')
      useLabelsStore(pinia).labels = [makeLabel({ id: 2, slug: 'backend' })]
      await flushPromises()
      expect(wrapper.findAll('[data-test="label-row"]').map((r) => r.attributes('data-slug'))).toEqual(['backend'])
      expect(wrapper.find('[data-test="label-delete-confirm"]').exists()).toBe(false)
      // The id comes back (reloaded or recreated): no stale confirmation.
      useLabelsStore(pinia).labels = [makeLabel({ id: 1, slug: 'urgente' }), makeLabel({ id: 2, slug: 'backend' })]
      await flushPromises()
      expect(wrapper.find('[data-test="label-delete-confirm"]').exists()).toBe(false)
    })

    it('os botões de cada linha dizem de qual etiqueta são', () => {
      const { wrapper } = mountPrefs()
      const row = rowOf(wrapper, 'urgente')
      expect(row.find('[data-test="label-delete"]').attributes('aria-label')).toBe('Apagar urgente')
      expect(row.find('[data-test="label-edit-slug"]').attributes('aria-label')).toBe('Nome de urgente')
      expect(row.find('[data-test="label-save"]').exists()).toBe(false)
    })
  })

  describe('etiquetas sem uso', () => {
    const group = (wrapper: VueWrapper) => wrapper.find('[data-test="label-unused-group"]')

    it('ficam num grupo à parte, com a contagem', () => {
      const { wrapper } = mountPrefs()
      expect(group(wrapper).exists()).toBe(true)
      expect(group(wrapper).findAll('[data-test="label-row"]').map((r) => r.attributes('data-slug'))).toEqual(['zeta', 'omega'])
      expect(group(wrapper).text()).toContain('Sem uso')
      expect(group(wrapper).find('[data-test="label-delete-unused"]').text()).toBe('Apagar as 2 sem uso')
      expect(group(wrapper).find('[data-test="label-row"][data-slug="urgente"]').exists()).toBe(false)
    })

    it('sem nenhuma, o grupo não aparece', () => {
      useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', label_ids: [1, 2, 3, 4] })])
      const { wrapper } = mountPrefs()
      expect(group(wrapper).exists()).toBe(false)
      expect(wrapper.find('[data-test="label-delete-unused"]').exists()).toBe(false)
    })

    it('com uma só, o botão diz "Apagar a 1 sem uso"', () => {
      useLabelsStore(pinia).labels = [makeLabel({ id: 1, slug: 'urgente' }), makeLabel({ id: 3, slug: 'zeta' })]
      const { wrapper } = mountPrefs()
      expect(group(wrapper).find('[data-test="label-delete-unused"]').text()).toBe('Apagar a 1 sem uso')
    })

    it('pede confirmação listando os nomes e só então apaga cada uma', async () => {
      const { wrapper, fetchMock } = mountPrefs({
        'DELETE /api/labels/3': () => new Response(null, { status: 204 }),
        'DELETE /api/labels/4': () => new Response(null, { status: 204 }),
      })
      await wrapper.find('[data-test="label-delete-unused"]').trigger('click')
      const dialog = wrapper.find('[role="dialog"]')
      expect(dialog.exists()).toBe(true)
      expect(dialog.text()).toContain('zeta')
      expect(dialog.text()).toContain('omega')
      expect(dialog.text()).not.toContain('urgente')
      expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'DELETE')).toHaveLength(0)
      await dialog.find('[data-test="confirm-ok"]').trigger('click')
      await flushPromises()
      expect(calls(fetchMock, 'DELETE /api/labels/3')).toHaveLength(1)
      expect(calls(fetchMock, 'DELETE /api/labels/4')).toHaveLength(1)
      expect(useLabelsStore(pinia).labels.map((l) => l.slug)).toEqual(['backend', 'urgente'])
      expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
      expect(group(wrapper).exists()).toBe(false)
    })

    it('cancelar não apaga nada', async () => {
      const { wrapper, fetchMock } = mountPrefs()
      await wrapper.find('[data-test="label-delete-unused"]').trigger('click')
      await wrapper.find('[role="dialog"] [data-test="confirm-cancel"]').trigger('click')
      expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
      expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'DELETE')).toHaveLength(0)
      expect(useLabelsStore(pinia).labels).toHaveLength(4)
    })

    it('se a segunda falhar, a primeira sai, a outra fica e o erro aparece', async () => {
      const { wrapper } = mountPrefs({
        'DELETE /api/labels/3': () => new Response(null, { status: 204 }),
        'DELETE /api/labels/4': () => jsonResponse({ detail: 'Não deu.' }, 500),
      })
      await wrapper.find('[data-test="label-delete-unused"]').trigger('click')
      await wrapper.find('[role="dialog"] [data-test="confirm-ok"]').trigger('click')
      await flushPromises()
      expect(useLabelsStore(pinia).labels.map((l) => l.slug)).toEqual(['backend', 'urgente', 'omega'])
      expect(group(wrapper).findAll('[data-test="label-row"]').map((r) => r.attributes('data-slug'))).toEqual(['omega'])
      expect(group(wrapper).find('[data-test="label-error"]').text()).toContain('Não deu.')
      expect(group(wrapper).find('[data-test="label-delete-unused"]').text()).toBe('Apagar a 1 sem uso')
      expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    })
  })

  describe('criar', () => {
    const slugField = (wrapper: VueWrapper) => wrapper.find('[data-test="label-create-slug"]')

    it('cria com o nome e a cor escolhida e limpa o campo', async () => {
      const { wrapper, fetchMock } = mountPrefs({
        'POST /api/labels': () => jsonResponse(makeLabel({ id: 9, slug: 'nova', color: '#ffd866' }), 201),
      })
      await slugField(wrapper).setValue('nova')
      await wrapper.find('[data-test="label-create-form"] [data-test="palette-color"][data-color="#ffd866"]').trigger('click')
      await wrapper.find('[data-test="label-create"]').trigger('click')
      await flushPromises()
      const posts = calls(fetchMock, 'POST /api/labels')
      expect(posts).toHaveLength(1)
      expect(bodyOf(posts[0]!)).toEqual({ slug: 'nova', color: '#ffd866' })
      expect(useLabelsStore(pinia).byId(9)?.slug).toBe('nova')
      expect((slugField(wrapper).element as HTMLInputElement).value).toBe('')
    })

    it('Enter no campo também cria', async () => {
      const { wrapper, fetchMock } = mountPrefs({
        'POST /api/labels': () => jsonResponse(makeLabel({ id: 9, slug: 'nova' }), 201),
      })
      await slugField(wrapper).setValue('nova')
      await slugField(wrapper).trigger('keydown', { key: 'Enter' })
      await flushPromises()
      expect(calls(fetchMock, 'POST /api/labels')).toHaveLength(1)
    })

    it('com nome vazio não chama a API', async () => {
      const { wrapper, fetchMock } = mountPrefs()
      await wrapper.find('[data-test="label-create"]').trigger('click')
      await slugField(wrapper).setValue('   ')
      await slugField(wrapper).trigger('keydown', { key: 'Enter' })
      await flushPromises()
      expect(calls(fetchMock, 'POST /api/labels')).toHaveLength(0)
    })

    it('erro ao criar aparece ao lado do formulário e o nome fica no campo', async () => {
      const { wrapper } = mountPrefs({
        'POST /api/labels': () => jsonResponse({ detail: 'Já existe uma etiqueta com esse slug.' }, 409),
      })
      await slugField(wrapper).setValue('urgente')
      await wrapper.find('[data-test="label-create"]').trigger('click')
      await flushPromises()
      expect(wrapper.find('[data-test="label-create-form"] [data-test="label-error"]').text()).toBe('Já existe uma etiqueta com esse slug.')
      expect((slugField(wrapper).element as HTMLInputElement).value).toBe('urgente')
    })

    it('a linha de criação aparece mesmo sem etiquetas', () => {
      useLabelsStore(pinia).labels = []
      const { wrapper } = mountPrefs()
      expect(slugField(wrapper).exists()).toBe(true)
      expect(wrapper.text()).toContain('Nenhuma etiqueta')
      expect(wrapper.find('[data-test="label-unused-group"]').exists()).toBe(false)
    })
  })
})
