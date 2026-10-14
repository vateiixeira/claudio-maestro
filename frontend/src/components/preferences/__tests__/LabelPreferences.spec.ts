import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
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
  useLabelsStore(pinia).labels = [makeLabel({ id: 1, slug: 'urgente', color: '#ef4444' }), makeLabel({ id: 2, slug: 'backend' })]
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

describe('preferências de etiquetas', () => {
  it('lista as etiquetas com quantas conversas usam cada uma', () => {
    const { wrapper } = mountPrefs()
    const rows = wrapper.findAll('[data-test="label-row"]')
    expect(rows.map((r) => r.attributes('data-slug'))).toEqual(['urgente', 'backend'])
    expect(rows[0].text()).toContain('2 conversas')
    expect(rows[1].text()).toContain('1 conversa')
  })

  it('salva o novo slug e a nova cor', async () => {
    const { wrapper, fetchMock } = mountPrefs({
      'PATCH /api/labels/1': () => jsonResponse(makeLabel({ id: 1, slug: 'critico', color: '#000000' })),
    })
    const row = wrapper.findAll('[data-test="label-row"]')[0]
    await row.find('[data-test="label-edit-slug"]').setValue('critico')
    await row.find('[data-test="label-edit-color"]').setValue('#000000')
    await row.find('[data-test="label-save"]').trigger('click')
    await flushPromises()
    const call = fetchMock.mock.calls.find(([url, init]) => `${init?.method} ${url}` === 'PATCH /api/labels/1')!
    expect(JSON.parse(String(call[1]?.body))).toEqual({ slug: 'critico', color: '#000000' })
    expect(useLabelsStore(pinia).byId(1)?.slug).toBe('critico')
  })

  it('o botão Salvar só liga quando algo mudou', async () => {
    const { wrapper } = mountPrefs()
    const row = wrapper.findAll('[data-test="label-row"]')[0]
    expect(row.find('[data-test="label-save"]').attributes('disabled')).toBeDefined()
    await row.find('[data-test="label-edit-slug"]').setValue('outro')
    expect(row.find('[data-test="label-save"]').attributes('disabled')).toBeUndefined()
  })

  it('mostra o erro de slug repetido na própria linha', async () => {
    const { wrapper } = mountPrefs({
      'PATCH /api/labels/2': () => jsonResponse({ detail: 'Já existe uma etiqueta com esse slug.' }, 409),
    })
    const row = wrapper.findAll('[data-test="label-row"]')[1]
    await row.find('[data-test="label-edit-slug"]').setValue('urgente')
    await row.find('[data-test="label-save"]').trigger('click')
    await flushPromises()
    expect(row.find('[data-test="label-error"]').text()).toBe('Já existe uma etiqueta com esse slug.')
  })

  it('apagar pede confirmação, diz quantas conversas perdem a etiqueta e só então apaga', async () => {
    const { wrapper, fetchMock } = mountPrefs({
      'DELETE /api/labels/1': () => new Response(null, { status: 204 }),
    })
    const deletes = () => fetchMock.mock.calls.filter(([, init]) => init?.method === 'DELETE')
    const row = wrapper.findAll('[data-test="label-row"]')[0]
    expect(row.text()).not.toContain('tira a etiqueta')
    await row.find('[data-test="label-delete"]').trigger('click')
    expect(row.text()).toContain('tira a etiqueta de 2 conversas')
    expect(deletes()).toHaveLength(0)
    await row.find('[data-test="label-delete-confirm"]').trigger('click')
    await flushPromises()
    expect(deletes()).toHaveLength(1)
    expect(deletes()[0]![0]).toBe('/api/labels/1')
    expect(useLabelsStore(pinia).byId(1)).toBeUndefined()
  })

  it('o rascunho acompanha o catálogo recarregado, menos quando há edição pendente', async () => {
    const { wrapper } = mountPrefs()
    const slugOf = (i: number) => (wrapper.findAll('[data-test="label-row"]')[i]!.find('[data-test="label-edit-slug"]').element as HTMLInputElement).value
    await wrapper.findAll('[data-test="label-row"]')[1]!.find('[data-test="label-edit-slug"]').setValue('meu-rascunho')
    // Another tab renames both labels.
    useLabelsStore(pinia).labels = [makeLabel({ id: 1, slug: 'outro-nome', color: '#ef4444' }), makeLabel({ id: 2, slug: 'novo-backend' })]
    await flushPromises()
    expect(slugOf(0)).toBe('outro-nome')
    expect(wrapper.findAll('[data-test="label-row"]')[0]!.find('[data-test="label-save"]').attributes('disabled')).toBeDefined()
    expect(slugOf(1)).toBe('meu-rascunho')
  })

  it('uma etiqueta apagada em outra aba some da lista e fecha a confirmação', async () => {
    const { wrapper } = mountPrefs()
    await wrapper.findAll('[data-test="label-row"]')[0]!.find('[data-test="label-delete"]').trigger('click')
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
    const row = wrapper.findAll('[data-test="label-row"]')[0]!
    expect(row.find('[data-test="label-save"]').attributes('aria-label')).toBe('Salvar urgente')
    expect(row.find('[data-test="label-delete"]').attributes('aria-label')).toBe('Apagar urgente')
  })

  it('sem etiquetas explica como criar uma', () => {
    useLabelsStore(pinia).labels = []
    const { wrapper } = mountPrefs()
    expect(wrapper.text()).toContain('Nenhuma etiqueta')
  })
})
