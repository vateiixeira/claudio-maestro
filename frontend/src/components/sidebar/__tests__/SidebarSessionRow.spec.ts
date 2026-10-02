import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import SidebarSessionRow from '../SidebarSessionRow.vue'
import { createAppRouter } from '../../../router'
import { useProjectsStore } from '../../../stores/projects'
import { makeProject, makeSession } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia
beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
})

async function mountRow(overrides: Parameters<typeof makeSession>[0], path = '/inbox', extraProps: Record<string, unknown> = {}) {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  await router.isReady()
  const wrapper = mount(SidebarSessionRow, { props: { session: makeSession(overrides), ...extraProps }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return wrapper
}

describe('linha de conversa do menu', () => {
  it('esconde o quadradinho do projeto com hideProject', async () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'loja-online' })]
    const wrapper = await mountRow({ project_id: 1 }, '/inbox', { hideProject: true })
    expect(wrapper.find('[data-test="row-project"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="row-title"]').exists()).toBe(true)
  })

  it('mostra o triângulo discreto quando a conversa aguarda sem novidade', async () => {
    const wrapper = await mountRow({ display_state: 'waiting', unread: false })
    expect(wrapper.find('svg').classes()).toContain('stroke-fg-subtle')
    expect(wrapper.find('svg').classes()).not.toContain('stroke-secondary')
  })

  it('mostra o triângulo laranja quando a conversa aguarda com novidade', async () => {
    const wrapper = await mountRow({ display_state: 'waiting', unread: true })
    expect(wrapper.find('svg').classes()).toContain('stroke-secondary')
    expect(wrapper.find('svg').classes()).not.toContain('stroke-fg-subtle')
  })

  it('mantém o triângulo laranja quando há pergunta, permissão ou plano esperando, mesmo vista', async () => {
    for (const kind of ['tool', 'question', 'plan'] as const) {
      const wrapper = await mountRow({ display_state: 'waiting', unread: false, pending_kind: kind })
      expect(wrapper.find('svg').classes()).toContain('stroke-secondary')
    }
  })

  it('mantém o triângulo laranja quando a conversa está com erro, mesmo vista', async () => {
    const wrapper = await mountRow({ display_state: 'waiting', unread: false, state: 'error' })
    expect(wrapper.find('svg').classes()).toContain('stroke-secondary')
  })

  it('usa fundo card na linha atual e fg-muted nas demais', async () => {
    const current = await mountRow({ session_id: 'x1' }, '/sessions/x1')
    expect(current.classes()).toContain('bg-card')
    expect(current.classes()).not.toContain('bg-elevated')
    const other = await mountRow({ session_id: 'x2' }, '/sessions/x1')
    expect(other.classes()).toContain('text-fg-muted')
    expect(other.classes()).not.toContain('bg-card')
  })

  it('mostra o projeto como quadradinho colorido, com o nome na dica e para leitor de tela', async () => {
    useProjectsStore(pinia).projects = [makeProject({ id: 1, name: 'loja-online', color: '#B28CFF' })]
    const wrapper = await mountRow({ project_id: 1 })
    const project = wrapper.find('[data-test="row-project"]')
    expect(project.attributes('title')).toBe('loja-online')
    expect(project.attributes('style')).toContain('background-color')
    expect(project.find('.sr-only').text()).toBe('loja-online')
    const html = wrapper.html()
    expect(html.indexOf('row-title')).toBeLessThan(html.indexOf('row-project'))
  })
})
