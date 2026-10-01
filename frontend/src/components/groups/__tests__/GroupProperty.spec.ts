import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import GroupProperty from '../GroupProperty.vue'
import { useGroupsStore } from '../../../stores/groups'
import { useSessionsStore } from '../../../stores/sessions'
import { jsonResponse, makeGroup, makeSession, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  useGroupsStore(pinia).groups = [
    // A is newer than B, so sortGroups puts it first.
    makeGroup({ id: 1, name: 'A', project_id: 1, created_at: 200 }),
    makeGroup({ id: 2, name: 'B', project_id: 1, created_at: 100 }),
    makeGroup({ id: 3, name: 'X', project_id: 2 }),
  ]
})
afterEach(() => vi.unstubAllGlobals())

type Handlers = Record<string, (init: RequestInit | undefined) => Response | Promise<Response>>

function mountProperty(handlers: Handlers = {}, groupId: number | null = null) {
  useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', group_id: groupId })])
  const fetchMock = routeFetch(handlers)
  vi.stubGlobal('fetch', fetchMock)
  const Host = { components: { GroupProperty }, template: '<dl><GroupProperty session-id="s1" :project-id="1" /></dl>' }
  const wrapper = mount(Host, { global: { plugins: [pinia] }, attachTo: document.body })
  return { wrapper, fetchMock }
}

const bodies = (fetchMock: ReturnType<typeof routeFetch>, key: string) =>
  fetchMock.mock.calls
    .filter(([url, init]) => `${init?.method ?? 'GET'} ${url}` === key)
    .map(([, init]) => JSON.parse(String(init?.body)))

describe('propriedade Agrupador', () => {
  it('lista Nenhum, os agrupadores do projeto e Novo agrupador', () => {
    const { wrapper } = mountProperty()
    const labels = wrapper.findAll('[data-test="prop-group"] option').map((o) => o.text())
    expect(labels).toEqual(['Nenhum', 'A', 'B', 'Novo agrupador…'])
  })

  it('seleciona o agrupador da sessão e ignora um desconhecido', () => {
    const known = mountProperty({}, 2)
    expect((known.wrapper.find('[data-test="prop-group"]').element as HTMLSelectElement).value).toBe('2')
    known.wrapper.unmount()
    const unknown = mountProperty({}, 99)
    expect((unknown.wrapper.find('[data-test="prop-group"]').element as HTMLSelectElement).value).toBe('')
  })

  it('agrupador de outro projeto cai em Nenhum, sem deixar o select em branco', () => {
    const { wrapper } = mountProperty({}, 3)
    const select = wrapper.find('[data-test="prop-group"]').element as HTMLSelectElement
    expect(select.value).toBe('')
    expect(select.selectedOptions[0]?.text).toBe('Nenhum')
  })

  it('move a sessão e tira do agrupador', async () => {
    const { wrapper, fetchMock } = mountProperty({
      'PATCH /api/sessions/s1': (init) => jsonResponse(makeSession({ session_id: 's1', group_id: JSON.parse(String(init?.body)).group_id })),
    })
    await wrapper.find('[data-test="prop-group"]').setValue('1')
    await flushPromises()
    await wrapper.find('[data-test="prop-group"]').setValue('')
    await flushPromises()
    expect(bodies(fetchMock, 'PATCH /api/sessions/s1')).toEqual([{ group_id: 1 }, { group_id: null }])
  })

  it('cria um agrupador novo e move a sessão para ele', async () => {
    const { wrapper, fetchMock } = mountProperty({
      'POST /api/projects/1/groups': () => jsonResponse(makeGroup({ id: 5, name: 'Novo' }), 201),
      'PATCH /api/sessions/s1': () => jsonResponse(makeSession({ session_id: 's1', group_id: 5 })),
    })
    await wrapper.find('[data-test="prop-group"]').setValue('__new__')
    const input = wrapper.find('[data-test="prop-group-new"]')
    expect(input.exists()).toBe(true)
    expect(document.activeElement).toBe(input.element)
    await input.setValue('Novo')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(bodies(fetchMock, 'POST /api/projects/1/groups')).toEqual([{ name: 'Novo' }])
    expect(bodies(fetchMock, 'PATCH /api/sessions/s1')).toEqual([{ group_id: 5 }])
    expect(wrapper.find('[data-test="prop-group-new"]').exists()).toBe(false)
  })

  it('o select e o campo de nome têm name e id únicos por sessão', async () => {
    const { wrapper } = mountProperty()
    const select = wrapper.find('[data-test="prop-group"]')
    expect(select.attributes('name')).toBe('group')
    expect(select.attributes('id')).toBe('prop-group-s1')
    await select.setValue('__new__')
    const input = wrapper.find('[data-test="prop-group-new"]')
    expect(input.attributes('name')).toBe('group-name')
    expect(input.attributes('id')).toBe('prop-group-new-s1')
  })

  it('mostra o erro da criação, mantém o campo aberto e não move', async () => {
    const { wrapper, fetchMock } = mountProperty({
      'POST /api/projects/1/groups': () => jsonResponse({ detail: 'Já existe um agrupador com esse nome neste projeto.' }, 409),
    })
    await wrapper.find('[data-test="prop-group"]').setValue('__new__')
    const input = wrapper.find('[data-test="prop-group-new"]')
    await input.setValue('A')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toBe('Já existe um agrupador com esse nome neste projeto.')
    expect(wrapper.find('[role="alert"]').classes()).toContain('text-diff-del-fg')
    expect(wrapper.find('[data-test="prop-group-new"]').exists()).toBe(true)
    expect(bodies(fetchMock, 'PATCH /api/sessions/s1')).toEqual([])
  })
})
