import { afterEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import AgentsGithub from '../AgentsGithub.vue'
import { jsonResponse, routeFetch } from '../../../test/factories'

const state = { login: 'vini', secret_set: true, hooks_port: 0, queued: 2 }
enableAutoUnmount(afterEach)
afterEach(() => vi.unstubAllGlobals())
async function setup(save = () => jsonResponse({ ...state, login: 'novo' })) {
  const fetch = routeFetch({
    'GET /api/specialists/github': () => jsonResponse(state),
    'PUT /api/specialists/github': save,
  })
  vi.stubGlobal('fetch', fetch)
  const wrapper = mount(AgentsGithub)
  await flushPromises()
  return { wrapper, fetch }
}
describe('comentários do GitHub', () => {
  it('mostra receptor desligado, fila e segredo definido sem preenchê-lo', async () => {
    const { wrapper } = await setup()
    expect(wrapper.text()).toContain('Receptor desligado')
    expect(wrapper.text()).toContain('2 comentários na fila')
    expect(wrapper.text()).toContain('definido')
    expect(wrapper.find('input[type="password"]').exists()).toBe(false)
    await wrapper.get('[data-test="github-secret-change"]').trigger('click')
    expect(wrapper.get<HTMLInputElement>('[data-test="github-secret"]').element.value).toBe('')
  })
  it('salva login e segredo e limpa o valor depois de salvar', async () => {
    const { wrapper, fetch } = await setup()
    await wrapper.get('[data-test="github-login"]').setValue('novo')
    await wrapper.get('[data-test="github-secret-change"]').trigger('click')
    await wrapper.get('[data-test="github-secret"]').setValue('segredo-local')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    const call = fetch.mock.calls.find(([, init]) => init?.method === 'PUT')!
    expect(JSON.parse(String(call[1]?.body))).toEqual({ login: 'novo', secret: 'segredo-local' })
    expect(wrapper.html()).not.toContain('segredo-local')
    expect(wrapper.text()).toContain('Salvo')
  })
  it('mostra o erro do servidor e permite corrigir o login', async () => {
    const { wrapper } = await setup(() => jsonResponse({ detail: 'Login inválido.' }, 422))
    await wrapper.get('[data-test="github-login"]').setValue('inválido!')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('Login inválido.')
    expect(wrapper.get<HTMLInputElement>('[data-test="github-login"]').element.value).toBe('inválido!')
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeUndefined()
  })
})
