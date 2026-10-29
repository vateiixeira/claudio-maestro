import { afterEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import GithubPreferences from '../GithubPreferences.vue'
import type { GithubSettings } from '../../../types/org'
import { jsonResponse, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
afterEach(() => vi.unstubAllGlobals())

const base: GithubSettings = { login: 'vini', secret_set: true, hooks_port: 6670, queued: 2 }

async function setup(state: GithubSettings = base, save: (body: unknown) => Response = (body) => jsonResponse({ ...state, ...(body as object), secret_set: true })) {
  const fetch = routeFetch({
    'GET /api/agents-github': () => jsonResponse(state),
    'PUT /api/agents-github': (init) => save(JSON.parse(String(init?.body))),
  })
  vi.stubGlobal('fetch', fetch)
  const wrapper = mount(GithubPreferences)
  await flushPromises()
  const puts = () => fetch.mock.calls.filter(([, init]) => init?.method === 'PUT').map(([, init]) => JSON.parse(String(init?.body)))
  return { wrapper, puts }
}

describe('preferências do GitHub', () => {
  it('mostra o login salvo e "Segredo do webhook: definido" quando secret_set é true', async () => {
    const { wrapper } = await setup()
    expect(wrapper.get<HTMLInputElement>('[data-test="github-login"]').element.value).toBe('vini')
    expect(wrapper.text()).toContain('Segredo do webhook: definido')
    expect(wrapper.find('[data-test="github-secret"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="github-status"]').text()).toContain('Recebendo na porta 6670 · 2 comentários na fila')
  })

  it('pede o segredo quando ainda não está definido', async () => {
    const { wrapper } = await setup({ login: null, secret_set: false, hooks_port: null, queued: 0 })
    expect(wrapper.find('[data-test="github-secret"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="github-status"]').text()).toContain('Receptor desligado (defina MAESTRO_HOOKS_PORT)')
  })

  it('salva só o login quando o segredo já existe', async () => {
    const { wrapper, puts } = await setup()
    await wrapper.get('[data-test="github-login"]').setValue('vini-2')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(puts()).toEqual([{ login: 'vini-2' }])
    expect(wrapper.text()).toContain('Salvo')
  })

  it('salva login e segredo quando o segredo foi digitado', async () => {
    const { wrapper, puts } = await setup()
    await wrapper.get('[data-test="github-secret-change"]').trigger('click')
    await wrapper.get('[data-test="github-login"]').setValue('vini-3')
    await wrapper.get('[data-test="github-secret"]').setValue('segredo-de-teste-com-20-chars')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(puts()).toEqual([{ login: 'vini-3', secret: 'segredo-de-teste-com-20-chars' }])
    expect(wrapper.find('[data-test="github-secret"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('definido')
    expect(wrapper.html()).not.toContain('segredo-de-teste-com-20-chars')
  })

  it('mostra o erro da API e mantém o que foi digitado', async () => {
    const { wrapper } = await setup(base, () => jsonResponse({ detail: 'Login ou segredo inválido.' }, 422))
    await wrapper.get('[data-test="github-login"]').setValue('inválido!')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('Login ou segredo inválido.')
    expect(wrapper.get<HTMLInputElement>('[data-test="github-login"]').element.value).toBe('inválido!')
  })
})
