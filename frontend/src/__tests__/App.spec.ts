import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import App from '../App.vue'

afterEach(() => vi.unstubAllGlobals())

describe('App', () => {
  it('mostra a marca e o backend conectado', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ status: 'ok' }))))
    const wrapper = mount(App)
    await flushPromises()
    expect(wrapper.text()).toContain('Vini7 Vibing')
    expect(wrapper.text()).toContain('Backend conectado')
    expect(fetch).toHaveBeenCalledWith('/api/health')
  })

  it('avisa quando o backend não responde', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline') }))
    const wrapper = mount(App)
    await flushPromises()
    expect(wrapper.text()).toContain('Backend indisponível')
  })
})
