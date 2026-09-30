import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import ConversationRow from '../ConversationRow.vue'
import { createAppRouter } from '../../../router'
import { useGitStore } from '../../../stores/git'
import { useProjectsStore } from '../../../stores/projects'
import { jsonResponse, makeGitRepo, makeProject, makeSession, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'loja-online', color: '#B28CFF' })]
  projects.loaded = true
  useGitStore(pinia).set(1, [makeGitRepo({ branch: 'develop' })])
})
afterEach(() => vi.unstubAllGlobals())

function mountRow(session = makeSession(), variant?: 'inbox' | 'list' | 'compact') {
  const router = createAppRouter(createMemoryHistory())
  return mount(ConversationRow, { props: { session, variant }, global: { plugins: [pinia, router] } })
}

describe('linha de conversa', () => {
  it('mostra título, projeto, branch e tempo, e abre a conversa', () => {
    const wrapper = mountRow(makeSession({ session_id: 'abc', title: 'Corrigir login' }))

    expect(wrapper.find('[data-test="row-link"]').text()).toBe('Corrigir login')
    expect(wrapper.find('[data-test="row-link"]').attributes('href')).toBe('/sessions/abc')
    expect(wrapper.find('[data-test="row-project"]').text()).toContain('loja-online')
    expect(wrapper.find('[data-test="row-branch"]').text()).toContain('develop')
  })

  it('linha da lista mostra a worktree no lugar do branch', () => {
    const wrapper = mountRow(makeSession({  worktree_name: 'melhorias', worktree_path: '/p/.claude/worktrees/melhorias', git_branch: 'worktree-melhorias' }))

    expect(wrapper.find('[data-test="row-branch"]').text()).toContain('worktree melhorias · worktree-melhorias')
    expect(wrapper.find('[data-test="row-branch"]').text()).not.toContain('develop')
  })

  it('mostra a bolinha de não lida e o motivo da espera', () => {
    const wrapper = mountRow(makeSession({ unread: true, display_state: 'waiting', state: 'awaiting_decision', pending_kind: 'question' }))

    expect(wrapper.find('[data-test="unread-dot"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="waiting-reason"]').text()).toBe('Fez uma pergunta')
  })

  it('apaga o texto de finalizadas e oferece Reabrir', () => {
    const wrapper = mountRow(makeSession({ display_state: 'finished', finished: true }))

    expect(wrapper.find('[data-test="row-link"]').classes()).toContain('text-fg-muted')
    expect(wrapper.find('[data-test="row-reopen"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="row-finish"]').exists()).toBe(false)
  })

  it('finaliza pela ação da linha', async () => {
    const fetch = routeFetch({
      'PATCH /api/sessions/s1': () => jsonResponse(makeSession({ display_state: 'finished', finished: true })),
    })
    vi.stubGlobal('fetch', fetch)
    const wrapper = mountRow(makeSession({ display_state: 'waiting' }))

    await wrapper.find('[data-test="row-finish"]').trigger('click')
    await flushPromises()

    expect(JSON.parse(fetch.mock.calls[0]![1]!.body as string)).toEqual({ finished: true })
  })

  it('marca como lida só na Inbox', async () => {
    const fetch = routeFetch({ 'POST /api/sessions/s1/seen': () => jsonResponse(makeSession()) })
    vi.stubGlobal('fetch', fetch)

    expect(mountRow(makeSession({ unread: true }), 'list').find('[data-test="row-mark-read"]').exists()).toBe(false)
    const inbox = mountRow(makeSession({ unread: true }), 'inbox')
    await inbox.find('[data-test="row-mark-read"]').trigger('click')
    await flushPromises()

    expect(fetch).toHaveBeenCalledOnce()
  })

  it('a variante compacta não tem ações', () => {
    const wrapper = mountRow(makeSession({ unread: true }), 'compact')
    expect(wrapper.find('[data-test="row-finish"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="row-mark-read"]').exists()).toBe(false)
  })

  it('avisa o erro de uma ação', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'PATCH /api/sessions/s1': () => jsonResponse({ detail: 'Falhou.' }, 500) }))
    const wrapper = mountRow(makeSession({ display_state: 'waiting' }))

    await wrapper.find('[data-test="row-finish"]').trigger('click')
    await flushPromises()

    expect(wrapper.emitted('error')).toEqual([['Falhou.']])
  })

  describe('selo do plano', () => {
    const plan = { path: 'docs/plan.md', title: 'Plano', total: 12, done: 3, current: { number: 4, title: 'Criar o selo' } }

    it.each(['inbox', 'list', 'compact'] as const)('aparece depois do título na variante %s', (variant) => {
      const wrapper = mountRow(makeSession({ display_state: 'running', plan }), variant)
      const badge = wrapper.find('[data-test="plan-badge"]')

      expect(badge.exists()).toBe(true)
      expect(badge.text()).toContain('4/12')
      const html = wrapper.html()
      expect(html.indexOf('data-test="row-link"')).toBeLessThan(html.indexOf('data-test="plan-badge"'))
    })

    it('não empurra a coluna de horário: o título trunca e o selo não encolhe', () => {
      const wrapper = mountRow(makeSession({ title: 'Um título muito longo '.repeat(10), display_state: 'running', plan }))

      expect(wrapper.find('[data-test="row-link"]').classes()).toEqual(expect.arrayContaining(['min-w-0', 'truncate']))
      expect(wrapper.find('[data-test="row-title"]').classes()).toEqual(expect.arrayContaining(['min-w-0', 'grow']))
      expect(wrapper.find('[data-test="plan-badge"]').classes()).toContain('shrink-0')
      expect(wrapper.find('.text-right').classes()).toContain('w-20')
    })

    it('repete a posição da tarefa no title do link da linha, que cobre o selo', () => {
      const wrapper = mountRow(makeSession({ display_state: 'running', plan }))
      expect(wrapper.find('[data-test="row-link"]').attributes('title')).toBe('Tarefa 4 de 12: Criar o selo')
      expect(wrapper.find('[data-test="plan-badge"]').attributes('aria-label')).toBe('Tarefa 4 de 12: Criar o selo')
    })

    it('não põe title no link quando não há plano visível', () => {
      expect(mountRow(makeSession({ plan: null })).find('[data-test="row-link"]').attributes('title')).toBeUndefined()
    })

    it('não aparece sem plano, com plano concluído nem em conversa finalizada', () => {
      const done = { ...plan, done: 12, current: null }

      expect(mountRow(makeSession({ plan: null })).find('[data-test="plan-badge"]').exists()).toBe(false)
      expect(mountRow(makeSession({ plan: done })).find('[data-test="plan-badge"]').exists()).toBe(false)
      expect(mountRow(makeSession({ display_state: 'finished', finished: true, plan })).find('[data-test="plan-badge"]').exists()).toBe(false)
    })
  })

  describe('alinhamento e foco', () => {
    it('as ações flutuam sobre o fim da linha em qualquer variante, sem tirar largura das colunas', () => {
      const rows = [
        mountRow(makeSession({ unread: true }), 'inbox'),
        mountRow(makeSession({ unread: false }), 'inbox'),
        mountRow(makeSession({ display_state: 'finished', finished: true }), 'list'),
      ]
      for (const row of rows) {
        const actions = row.find('[data-test="row-actions"]')
        expect(actions.classes()).toContain('absolute')
        expect(actions.classes()).not.toContain('shrink-0')
      }
    })

    it('as ações escondidas não recebem toque, e aparecem no hover, no foco e em telas sem hover', () => {
      const classes = mountRow(makeSession()).find('[data-test="row-actions"]').classes()
      expect(classes).toContain('opacity-0')
      expect(classes).toContain('pointer-events-none')
      expect(classes).toContain('group-hover:pointer-events-auto')
      expect(classes).toContain('focus-within:pointer-events-auto')
      expect(classes).toContain('group-focus-within:opacity-100')
      expect(classes).toContain('group-focus-within:pointer-events-auto')
      expect(classes).toContain('[@media(hover:none)]:opacity-100')
      expect(classes).toContain('[@media(hover:none)]:pointer-events-auto')
    })

    it('projeto, branch e horário têm largura fixa, também numa linha sem branch', () => {
      const withRepo = mountRow(makeSession({ project_id: 1 }))
      useGitStore(pinia).set(2, [])
      useProjectsStore(pinia).projects.push(makeProject({ id: 2, name: 'sem-git', path: '/x' }))
      const noRepo = mountRow(makeSession({ project_id: 2 }))

      for (const row of [withRepo, noRepo]) {
        expect(row.find('[data-test="row-project"]').classes()).toContain('w-36')
        expect(row.find('[data-test="row-branch"]').classes()).toContain('w-40')
        expect(row.find('.text-right').classes()).toContain('w-20')
      }
      expect(noRepo.find('[data-test="row-branch"]').text()).toBe('')
    })

    it('o link tem um anel visível quando recebe foco pelo teclado', () => {
      const link = mountRow().find('[data-test="row-link"]')
      expect(link.classes()).toEqual(expect.arrayContaining([
        'focus-visible:after:ring-2', 'focus-visible:after:ring-primary',
      ]))
    })
  })
})
