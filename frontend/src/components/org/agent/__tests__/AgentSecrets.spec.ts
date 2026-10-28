import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import AgentSecrets from '../AgentSecrets.vue'
import { jsonResponse, routeFetch } from '../../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
})
afterEach(() => vi.unstubAllGlobals())

async function mountSecrets(handlers: Parameters<typeof routeFetch>[0] = {}) {
  const fetch = routeFetch({ 'GET /api/agents/1/secrets': () => jsonResponse({ names: ['SENTRY_TOKEN'] }), ...handlers })
  vi.stubGlobal('fetch', fetch)
  const wrapper = mount(AgentSecrets, { props: { agentId: 1 }, global: { plugins: [pinia] }, attachTo: document.body })
  await flushPromises()
  return { wrapper, fetch }
}

const puts = (fetch: ReturnType<typeof routeFetch>) =>
  fetch.mock.calls.filter(([, init]) => init?.method === 'PUT').map(([, init]) => JSON.parse(String(init?.body)))

describe('AgentSecrets', () => {
  it('lista só os nomes e esconde os valores digitados', async () => {
    const { wrapper } = await mountSecrets()
    expect(wrapper.findAll('[data-test="secret-name"]').map((s) => s.text())).toEqual(['SENTRY_TOKEN'])
    const inputs = wrapper.findAll('[data-test="secrets"] input')
    expect(inputs.every((i) => i.attributes('type') === 'password' || i.attributes('data-test') === 'secret-new-name')).toBe(true)
  })

  it('adiciona um segredo e solta o valor do campo logo depois de enviar', async () => {
    const { wrapper, fetch } = await mountSecrets({ 'PUT /api/agents/1/secrets': () => jsonResponse({ names: ['SENTRY_TOKEN', 'DB_URL'] }) })
    await wrapper.get('[data-test="secret-new-name"]').setValue('DB_URL')
    const value = wrapper.get<HTMLInputElement>('[data-test="secret-new-value"]')
    await value.setValue('postgres://segredo-super-secreto')
    await wrapper.get('[data-test="secret-add"]').trigger('click')
    await flushPromises()
    expect(puts(fetch)).toEqual([{ values: { DB_URL: 'postgres://segredo-super-secreto' } }])
    expect(wrapper.findAll('[data-test="secret-name"]').map((s) => s.text())).toEqual(['SENTRY_TOKEN', 'DB_URL'])
    expect(value.element.value).toBe('')
    expect(wrapper.html()).not.toContain('segredo-super-secreto')
    expect(document.body.innerHTML).not.toContain('segredo-super-secreto')
  })

  it('troca o valor e remove um segredo', async () => {
    const { wrapper, fetch } = await mountSecrets({ 'PUT /api/agents/1/secrets': () => jsonResponse({ names: ['SENTRY_TOKEN'] }) })
    await wrapper.get('[data-test="secret-change"]').trigger('click')
    await wrapper.get('[data-test="secret-change-value"]').setValue('novo-valor')
    await wrapper.get('[data-test="secret-change-save"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="secret-remove"]').trigger('click')
    await flushPromises()
    expect(puts(fetch)).toEqual([{ values: { SENTRY_TOKEN: 'novo-valor' } }, { values: { SENTRY_TOKEN: null } }])
  })

  it('enviar com outro envio em andamento não apaga o valor digitado', async () => {
    let finish!: (r: Response) => void
    const { wrapper } = await mountSecrets({ 'PUT /api/agents/1/secrets': () => new Promise<Response>((resolve) => { finish = resolve }) })
    await wrapper.get('[data-test="secret-remove"]').trigger('click')
    await wrapper.get('[data-test="secret-new-name"]').setValue('OUTRO')
    await wrapper.get('[data-test="secret-new-value"]').setValue('v')
    await wrapper.get('[data-test="secrets"] form').trigger('submit')
    expect(wrapper.get<HTMLInputElement>('[data-test="secret-new-name"]').element.value).toBe('OUTRO')
    expect(wrapper.get<HTMLInputElement>('[data-test="secret-new-value"]').element.value).toBe('v')
    finish(jsonResponse({ names: [] }))
    await flushPromises()
  })

  it('erro da API aparece como alerta e o valor não volta para a tela', async () => {
    const { wrapper } = await mountSecrets({ 'PUT /api/agents/1/secrets': () => jsonResponse({ detail: 'O nome do segredo deve ter letras maiúsculas, números e _.' }, 422) })
    await wrapper.get('[data-test="secret-new-name"]').setValue('nome ruim')
    await wrapper.get('[data-test="secret-new-value"]').setValue('valor-que-nao-deve-aparecer')
    await wrapper.get('[data-test="secret-add"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="secret-error"]').attributes('role')).toBe('alert')
    expect(wrapper.get('[data-test="secret-error"]').text()).toContain('letras maiúsculas')
    expect(wrapper.get<HTMLInputElement>('[data-test="secret-new-value"]').element.value).toBe('')
    expect(wrapper.html()).not.toContain('valor-que-nao-deve-aparecer')
  })
})
