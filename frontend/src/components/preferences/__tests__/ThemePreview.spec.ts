import { afterEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import ThemePreview from '../ThemePreview.vue'

enableAutoUnmount(afterEach)

describe('prévia de sessão dos temas', () => {
  it('pinta a raiz com o tema recebido e some para leitores de tela e teclado', async () => {
    const w = mount(ThemePreview, { props: { themeId: 'dracula' } })
    expect(w.attributes('data-test')).toBe('theme-preview')
    expect(w.attributes('data-theme')).toBe('dracula')
    expect(w.attributes('aria-hidden')).toBe('true')
    expect(w.attributes('inert')).toBeDefined()
    await w.setProps({ themeId: 'monokai-pro' })
    expect(w.attributes('data-theme')).toBe('monokai-pro')
  })

  it('mostra uma conversa aberta: mensagem, resposta com código realçado, diff, permissão e barra de mensagem', () => {
    const w = mount(ThemePreview, { props: { themeId: 'maestro' } })
    expect(w.text()).toContain('Esperando você')
    expect(w.text()).toContain('redirectAfterLogin')
    expect(w.find('.markdown pre code .hljs-keyword').exists()).toBe(true)
    expect(w.findAll('[data-test="diff-line"]')).toHaveLength(5)
    expect(w.text()).toContain('Permitir uma vez')
    expect(w.text()).toContain('Enviar')
  })
})
