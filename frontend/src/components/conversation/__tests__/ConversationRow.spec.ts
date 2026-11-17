import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import ConversationRow from '../ConversationRow.vue'
import { createAppRouter } from '../../../router'
import { useGitStore } from '../../../stores/git'
import { useGroupsStore } from '../../../stores/groups'
import { useLabelsStore } from '../../../stores/labels'
import { useProjectsStore } from '../../../stores/projects'
import { useOrgStore } from '../../../stores/org'
import { jsonResponse, makeGitRepo, makeGroup, makeLabel, makeProject, makeSession, makeAgent, routeFetch } from '../../../test/factories'

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

function mountRow(session = makeSession(), variant?: 'inbox' | 'list', extra: Record<string, unknown> = {}) {
  const router = createAppRouter(createMemoryHistory())
  return mount(ConversationRow, { props: { session, variant, ...extra }, global: { plugins: [pinia, router] } })
}

describe('linha de conversa', () => {
  it('no projeto separa resumo e metadados do título sem limitar sua largura à metade', () => {
    const row = mountRow(makeSession({ title: 'Ajustar abertura da agenda', digest_short: 'Conferir disponibilidade', worktree_name: 'agenda', worktree_path: '/p/agenda', git_branch: 'perf/agenda', closure_verdict: 'incomplete' }), undefined, { projectContextId: 1 })
    expect(row.get('[data-test="row-link"]').classes()).not.toContain('max-w-[55%]')
    const details = row.get('[data-test="row-details"]')
    expect(details.get('[data-test="row-digest"]').text()).toBe('Conferir disponibilidade')
    expect(details.get('[data-test="row-branch"]').text()).toContain('agenda')
    expect(row.get('[data-test="row-situation"]').get('[data-test="closure-badge"]').text()).toBe('Entrega incompleta')
    expect(details.find('[data-test="row-link"]').exists()).toBe(false)
  })

  it('no contexto do projeto omite metadados redundantes, preservando worktree', () => {
    const row = mountRow(makeSession(), undefined, { projectContextId: 1 })
    expect(row.find('[data-test="row-project"]').exists()).toBe(false)
    expect(row.find('[data-test="row-branch"]').exists()).toBe(false)
    const worktree = mountRow(makeSession({ worktree_name: 'fix', worktree_path: '/p/fix', git_branch: 'fix' }), undefined, { projectContextId: 1 })
    expect(worktree.get('[data-test="row-branch"]').text()).toContain('fix')
  })

  it('conversa de outro projeto mantém sua identificação no contexto local', () => {
    const row = mountRow(makeSession(), undefined, { projectContextId: 2 })
    expect(row.find('[data-test="row-project"]').exists()).toBe(false)
    const tag = row.get('[data-test="row-details"]').get('[data-test="project-tag"]')
    expect(tag.text()).toContain('loja-online')
    expect(tag.get('[data-test="project-tag-branch"]').text()).toBe('develop')
  })

  it('mostra título, projeto, branch e tempo, e abre a conversa', () => {
    const wrapper = mountRow(makeSession({ session_id: 'abc', title: 'Corrigir login' }))

    expect(wrapper.find('[data-test="row-link"]').text()).toBe('Corrigir login')
    expect(wrapper.find('[data-test="row-link"]').attributes('href')).toBe('/sessions/abc')
    expect(wrapper.find('[data-test="row-project"] [data-test="project-tag"]').text()).toContain('loja-online')
    expect(wrapper.find('[data-test="project-tag-branch"]').text()).toBe('develop')
    expect(wrapper.find('[data-test="row-activity"]').text()).not.toBe('')
  })

  it('usa o destino recebido em vez da página da conversa', () => {
    const wrapper = mountRow(makeSession({ session_id: 'abc' }), undefined, {
      to: { name: 'project', params: { id: 1 }, query: { sessao: 'abc' } },
    })

    expect(wrapper.find('[data-test="row-link"]').attributes('href')).toBe('/projects/1?sessao=abc')
  })

  it('marca a linha aberta com destaque e aria-current', () => {
    const active = mountRow(makeSession(), undefined, { active: true })
    expect(active.find('[data-test="row-link"]').attributes('aria-current')).toBe('true')
    expect(active.get('[data-test="conversation-row"]').attributes('data-active')).toBe('true')

    const idle = mountRow(makeSession())
    expect(idle.find('[data-test="row-link"]').attributes('aria-current')).toBeUndefined()
    expect(idle.get('[data-test="conversation-row"]').attributes('data-active')).toBeUndefined()
  })

  it('linha da lista mostra a worktree no lugar do branch', () => {
    const wrapper = mountRow(makeSession({  worktree_name: 'melhorias', worktree_path: '/p/.claude/worktrees/melhorias', git_branch: 'worktree-melhorias' }))

    expect(wrapper.find('[data-test="project-tag-branch"]').text()).toContain('worktree melhorias · worktree-melhorias')
    expect(wrapper.find('[data-test="project-tag-branch"]').text()).not.toContain('develop')
  })

  it('marcada e não lida, sem pedido real: triângulo discreto e "Sua vez"', () => {
    const wrapper = mountRow(makeSession({ display_state: 'waiting', state: 'idle', unread: true, mark: 'on_hold' }))

    expect(wrapper.find('svg').classes()).toContain('stroke-fg-subtle')
    expect(wrapper.find('[data-test="waiting-reason"]').text()).toBe('Sua vez')
  })

  it('mostra o motivo da espera na coluna Situação, sem bolinha de não lida', () => {
    const wrapper = mountRow(makeSession({ unread: true, display_state: 'waiting', state: 'awaiting_decision', pending_kind: 'question' }))

    expect(wrapper.find('[data-test="unread-dot"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="row-situation"]').get('[data-test="waiting-reason"]').text()).toBe('Fez uma pergunta')
    expect(wrapper.get('[data-test="waiting-reason"]').classes()).toContain('text-secondary-soft')
    expect(wrapper.get('.sr-only').text()).toContain('com novidade')
  })

  it('não lida: título em text-fg e font-medium; lida: peso normal; finalizada: apagada', () => {
    const unread = mountRow(makeSession({ unread: true })).get('[data-test="row-link"]').classes()
    expect(unread).toEqual(expect.arrayContaining(['text-fg', 'font-medium']))
    const read = mountRow(makeSession({ unread: false })).get('[data-test="row-link"]').classes()
    expect(read).toContain('text-fg')
    expect(read).not.toContain('font-medium')
    expect(mountRow(makeSession({ display_state: 'finished', finished: true, unread: false })).get('[data-test="row-link"]').classes()).toContain('text-fg-muted')
  })

  it('espera comum, sem novidade: triângulo discreto e motivo neutro', () => {
    const wrapper = mountRow(makeSession({ display_state: 'waiting', state: 'idle', unread: false }))

    expect(wrapper.find('svg').classes()).toContain('stroke-fg-subtle')
    expect(wrapper.find('[data-test="waiting-reason"]').text()).toBe('Sua vez')
    expect(wrapper.find('[data-test="waiting-reason"]').classes()).toContain('text-fg-muted')
    expect(wrapper.find('[data-test="waiting-reason"]').classes()).not.toContain('text-secondary-soft')
  })

  it.each([
    ['não lida', { unread: true }],
    ['com plano pendente', { pending_kind: 'plan' as const }],
    ['com erro', { state: 'error' as const }],
  ])('espera que precisa de você (%s): triângulo e motivo laranja', (_, extra) => {
    const wrapper = mountRow(makeSession({ display_state: 'waiting', state: 'idle', unread: false, ...extra }))

    expect(wrapper.find('svg').classes()).toContain('stroke-secondary')
    expect(wrapper.find('[data-test="waiting-reason"]').classes()).toContain('text-secondary-soft')
  })

  it('no projeto o leitor de tela não repete o motivo da espera, que já está visível', () => {
    const row = mountRow(makeSession({ display_state: 'waiting', state: 'awaiting_decision', pending_kind: 'question' }), undefined, { projectContextId: 1 })
    expect(row.get('[data-test="waiting-reason"]').text()).toBe('Fez uma pergunta')
    expect(row.get('.sr-only').text()).toBe('Aguardando você')
  })

  it('leitor de tela: espera comum é "Sua vez" e a que pede você é "Aguardando você"', () => {
    const sr = (w: ReturnType<typeof mountRow>) => w.find('.sr-only').text()
    expect(sr(mountRow(makeSession({ display_state: 'waiting', state: 'idle' })))).toBe('Sua vez')
    expect(sr(mountRow(makeSession({ display_state: 'waiting', state: 'awaiting_decision', pending_kind: 'question' })))).toBe('Aguardando você')
    expect(sr(mountRow(makeSession({ display_state: 'running', state: 'running' })))).toBe('Em execução')
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

  it('mostra o selo de fechamento', () => {
    const session = makeSession({ display_state: 'waiting', closure_verdict: 'incomplete' })
    const full = mountRow(session)
    expect(full.get('[data-test="closure-badge"]').text()).toBe('Entrega incompleta')
    expect(full.find('[data-test="closure-dot"]').exists()).toBe(false)
    expect(mountRow(makeSession({ closure_verdict: null })).find('[data-test="closure-badge"]').exists()).toBe(false)
  })

  it('avisa o erro de uma ação', async () => {
    vi.stubGlobal('fetch', routeFetch({ 'PATCH /api/sessions/s1': () => jsonResponse({ detail: 'Falhou.' }, 500) }))
    const wrapper = mountRow(makeSession({ display_state: 'waiting' }))

    await wrapper.find('[data-test="row-finish"]').trigger('click')
    await flushPromises()

    expect(wrapper.emitted('error')).toEqual([['Falhou.']])
  })

  describe('plano na coluna Situação', () => {
    const plan = { path: 'docs/plan.md', title: 'Plano', total: 12, done: 3, current: { number: 4, title: 'Criar o selo' } }

    it.each(['inbox', 'list'] as const)('mostra as barrinhas do plano em row-situation na variante %s', (variant) => {
      const wrapper = mountRow(makeSession({ display_state: 'running', plan }), variant)
      const segments = wrapper.get('[data-test="row-situation"]').find('[data-test="plan-segments"]')

      expect(segments.exists()).toBe(true)
      expect(segments.attributes('aria-label')).toBe('Tarefa 4 de 12: Criar o selo')
      expect(wrapper.find('[data-test="plan-badge"]').exists()).toBe(false)
    })

    it('repete a posição da tarefa no title do link da linha, que cobre as barrinhas', () => {
      const wrapper = mountRow(makeSession({ display_state: 'running', plan }))
      expect(wrapper.find('[data-test="row-link"]').attributes('title')).toBe('Tarefa 4 de 12: Criar o selo')
    })

    it('não põe title no link quando não há plano visível', () => {
      expect(mountRow(makeSession({ plan: null })).find('[data-test="row-link"]').attributes('title')).toBeUndefined()
    })

    it('não aparece sem plano, com plano concluído nem em conversa finalizada', () => {
      const done = { ...plan, done: 12, current: null }

      expect(mountRow(makeSession({ plan: null })).find('[data-test="plan-segments"]').exists()).toBe(false)
      expect(mountRow(makeSession({ plan: done })).find('[data-test="plan-segments"]').exists()).toBe(false)
      expect(mountRow(makeSession({ display_state: 'finished', finished: true, plan })).find('[data-test="plan-segments"]').exists()).toBe(false)
    })
  })

  describe('grade de colunas', () => {
    const cols = 'md:grid-cols-[0.875rem_minmax(0,1fr)_11rem_10.5rem_4.25rem]'
    const childTests = (row: ReturnType<typeof mountRow>) =>
      Array.from(row.get('[data-test="conversation-row"]').element.children).map((c) => c.getAttribute('data-test'))

    it.each(['list', 'inbox'] as const)('variante %s: ícone, conversa, situação, projeto e atividade, nesta ordem', (variant) => {
      const row = mountRow(makeSession(), variant)
      const root = row.get('[data-test="conversation-row"]')
      expect(root.classes()).toContain('grid')
      expect(root.classes()).toContain(cols)
      const tests = childTests(row)
      expect(tests.filter(Boolean).slice(0, 4)).toEqual(['row-title', 'row-situation', 'row-project', 'row-activity'])
      expect(root.element.children[0]!.getAttribute('data-shape')).not.toBeNull()
    })

    it('abaixo de md a situação desce para baixo da conversa e o projeto some', () => {
      const row = mountRow(makeSession())
      expect(row.get('[data-test="conversation-row"]').classes()).toContain('grid-cols-[0.875rem_minmax(0,1fr)_auto]')
      expect(row.get('[data-test="row-project"]').classes()).toContain('hidden')
      expect(row.get('[data-test="row-situation"]').classes()).toEqual(expect.arrayContaining(['max-md:row-start-2', 'max-md:col-start-2']))
    })

    it('row-details vem depois do link e leva resumo, agente, agrupador e etiquetas', () => {
      useGroupsStore(pinia).groups = [makeGroup({ id: 2, name: 'Checkout' })]
      useLabelsStore(pinia).labels = [makeLabel({ id: 1, slug: 'et1' })]
      useOrgStore(pinia).agents = [makeAgent({ id: 4, name: 'Triagem' })]
      const row = mountRow(makeSession({ digest_short: 'Resumo curto', group_id: 2, label_ids: [1], agent_id: 4 }))
      const html = row.html()
      expect(html.indexOf('data-test="row-link"')).toBeLessThan(html.indexOf('data-test="row-details"'))
      const details = row.get('[data-test="row-details"]')
      expect(details.get('[data-test="row-digest"]').text()).toBe('Resumo curto')
      for (const id of ['group-tag', 'agent-badge', 'label-badge']) expect(details.find(`[data-test="${id}"]`).exists()).toBe(true)
    })

    it('situação traz, quando valem, plano, "Plano concluído", entrega incompleta e o motivo, nesta ordem', () => {
      const plan = { path: 'docs/plan.md', title: 'Plano', total: 5, done: 1, current: { number: 2, title: 'Seguir' } }
      const row = mountRow(makeSession({ display_state: 'waiting', state: 'awaiting_decision', pending_kind: 'question', plan, plan_done: true, closure_verdict: 'incomplete' }))
      const situation = row.get('[data-test="row-situation"]')
      const order = Array.from(situation.element.querySelectorAll('[data-test]')).map((e) => e.getAttribute('data-test')).filter((t) => ['plan-segments', 'row-plan-done', 'closure-badge', 'waiting-reason'].includes(t!))
      expect(order).toEqual(['plan-segments', 'row-plan-done', 'closure-badge', 'waiting-reason'])
      expect(situation.get('[data-test="row-plan-done"]').text()).toBe('Plano concluído')
    })

    it('o slot status substitui o motivo da espera dentro da situação', () => {
      const router = createAppRouter(createMemoryHistory())
      const wrapper = mount(ConversationRow, {
        props: { session: makeSession({ display_state: 'waiting' }), variant: 'inbox' },
        slots: { status: '<span data-test="decided">Negado</span>' },
        global: { plugins: [pinia, router] },
      })
      expect(wrapper.get('[data-test="row-situation"]').find('[data-test="decided"]').exists()).toBe(true)
      expect(wrapper.find('[data-test="waiting-reason"]').exists()).toBe(false)
    })

    it('a atividade fica alinhada à direita', () => {
      expect(mountRow(makeSession()).get('[data-test="row-activity"]').classes()).toContain('text-right')
    })

    it('no projeto: grade própria, situação à direita, sem coluna de projeto e título em font-medium', () => {
      const row = mountRow(makeSession({ closure_verdict: 'incomplete' }), undefined, { projectContextId: 1 })
      const root = row.get('[data-test="conversation-row"]')
      expect(root.classes()).toContain('grid')
      expect(row.find('[data-test="row-project"]').exists()).toBe(false)
      expect(row.get('[data-test="row-situation"]').classes()).toContain('md:justify-end')
      expect(row.get('[data-test="row-link"]').classes()).toContain('font-medium')
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

    it('projeto e atividade ocupam suas colunas mesmo numa linha sem branch', () => {
      useGitStore(pinia).set(2, [])
      useProjectsStore(pinia).projects.push(makeProject({ id: 2, name: 'sem-git', path: '/x' }))
      const noRepo = mountRow(makeSession({ project_id: 2 }))

      expect(noRepo.find('[data-test="row-project"]').exists()).toBe(true)
      expect(noRepo.find('[data-test="project-tag-branch"]').exists()).toBe(false)
      expect(noRepo.find('[data-test="row-activity"]').exists()).toBe(true)
    })

    it('o link tem um anel visível quando recebe foco pelo teclado', () => {
      const link = mountRow().find('[data-test="row-link"]')
      expect(link.classes()).toEqual(expect.arrayContaining([
        'focus-visible:after:ring-2', 'focus-visible:after:ring-primary',
      ]))
    })
  })
})

describe('etiqueta do agrupador na linha', () => {
  it('mostra o nome do agrupador conhecido e nada para um desconhecido', () => {
    useGroupsStore(pinia).groups = [makeGroup({ id: 2, name: 'Checkout' })]
    expect(mountRow(makeSession({ group_id: 2 })).find('[data-test="group-tag"]').text()).toContain('Checkout')
    expect(mountRow(makeSession({ group_id: 99 })).find('[data-test="group-tag"]').exists()).toBe(false)
    expect(mountRow(makeSession({ group_id: null })).find('[data-test="group-tag"]').exists()).toBe(false)
  })
})

describe('resumo na linha', () => {
  it('mostra a frase curta do resumo depois do título', async () => {
    const w = mountRow(makeSession({ digest_short: 'Executa o plano do agrupador' }))
    await flushPromises()
    expect(w.find('[data-test="row-digest"]').text()).toBe('Executa o plano do agrupador')
    expect(w.find('[data-test="row-link"]').classes()).toEqual(expect.arrayContaining(['truncate', 'min-w-0']))
  })

  it('sem resumo não mostra nada a mais', async () => {
    const w = mountRow(makeSession({ digest_short: null }))
    await flushPromises()
    expect(w.find('[data-test="row-digest"]').exists()).toBe(false)
    expect(w.find('[data-test="row-plan-done"]').exists()).toBe(false)
    expect(w.find('[data-test="row-link"]').classes()).not.toContain('max-w-[55%]')
  })

  it('mostra "Plano concluído"', async () => {
    const w = mountRow(makeSession({ plan_done: true }))
    await flushPromises()
    expect(w.find('[data-test="row-plan-done"]').text()).toBe('Plano concluído')
  })
})

describe('marcações na linha de conversa', () => {
  it('clique direito abre o menu de marcação no lugar do menu do navegador', async () => {
    const row = mountRow(makeSession({ session_id: 's1' }))
    const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 10, clientY: 20 })
    row.find('[data-test="conversation-row"]').element.dispatchEvent(event)
    await flushPromises()
    expect(event.defaultPrevented).toBe(true)
    expect(document.body.querySelector('[data-test="mark-popover"]')).not.toBeNull()
  })
  it('mostra os ícones de marcação e prioridade, como imagens com rótulo', () => {
    const row = mountRow(makeSession({ mark: 'blocked', priority: true }))
    const mark = row.find('[data-test="row-mark"]')
    expect(mark.attributes('role')).toBe('img')
    expect(mark.attributes('aria-label')).toBe('Bloqueada')
    const star = row.find('[data-test="row-priority"]')
    expect(star.attributes('role')).toBe('img')
    expect(star.classes()).toContain('text-fg-muted')
  })
  it('repete a marcação no title do link, que cobre o ícone', () => {
    const blocked = mountRow(makeSession({ mark: 'blocked', mark_note: 'esperando o deploy' }))
    expect(blocked.find('[data-test="row-link"]').attributes('title')).toBe('Bloqueada: esperando o deploy')
    const review = mountRow(makeSession({ mark: 'review' }))
    expect(review.find('[data-test="row-link"]').attributes('title')).toBe('Para revisar')
    const plan = { path: 'docs/plan.md', title: 'Plano', total: 12, done: 3, current: { number: 4, title: 'Criar o selo' } }
    const both = mountRow(makeSession({ mark: 'blocked', mark_note: 'deploy', display_state: 'running', plan }))
    expect(both.find('[data-test="row-link"]').attributes('title')).toBe('Bloqueada: deploy · Tarefa 4 de 12: Criar o selo')
  })
  it('sem marcação não mostra ícones', () => {
    const row = mountRow(makeSession())
    expect(row.find('[data-test="row-mark"]').exists()).toBe(false)
    expect(row.find('[data-test="row-priority"]').exists()).toBe(false)
  })
  it('pela tecla de menu (coordenadas 0,0) abre no canto inferior esquerdo da linha', async () => {
    const row = mountRow(makeSession({ session_id: 's1' }))
    const el = row.find('[data-test="conversation-row"]').element
    el.getBoundingClientRect = () => ({ left: 30, bottom: 50, top: 30, right: 130, width: 100, height: 20, x: 30, y: 30, toJSON: () => ({}) })
    el.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 0, clientY: 0 }))
    await flushPromises()
    const popover = document.body.querySelector<HTMLElement>('[data-test="mark-popover"]')!
    expect(popover.style.left).toBe('30px')
    expect(popover.style.top).toBe('50px')
  })

  it('com foco de teclado destaca a linha e mostra as ações sem passar o mouse', () => {
    const wrapper = mountRow(makeSession(), 'inbox', { focused: true })
    const row = wrapper.get('[data-test="conversation-row"]')
    expect(row.classes()).toContain('bg-card')
    expect(row.classes().join(' ')).toContain('inset_2px_0_0_var(--color-primary)')
    expect(row.attributes('data-focused')).toBe('true')
    expect(wrapper.get('[data-test="row-actions"]').classes()).toContain('opacity-100')
    expect(wrapper.get('[data-test="row-link"]').attributes('aria-current')).toBeUndefined()

    const idle = mountRow(makeSession(), 'inbox')
    expect(idle.get('[data-test="conversation-row"]').attributes('data-focused')).toBeUndefined()
    expect(idle.get('[data-test="row-actions"]').classes()).not.toContain('opacity-100')
  })

  it('aceita ações extras e um estado no lugar do motivo de espera', () => {
    const session = makeSession({ display_state: 'waiting', pending_kind: 'tool' })
    const plain = mountRow(session, 'inbox')
    expect(plain.find('[data-test="waiting-reason"]').exists()).toBe(true)

    const router = createAppRouter(createMemoryHistory())
    const wrapper = mount(ConversationRow, {
      props: { session, variant: 'inbox' },
      slots: { actions: '<button data-test="extra">Extra</button>', status: '<span data-test="decided">Negado</span>' },
      global: { plugins: [pinia, router] },
    })
    expect(wrapper.find('[data-test="row-actions"] [data-test="extra"]').exists()).toBe(true)
    expect(wrapper.get('[data-test="decided"]').text()).toBe('Negado')
    expect(wrapper.find('[data-test="waiting-reason"]').exists()).toBe(false)
  })
})

describe('etiquetas na linha de conversa', () => {
  const labelsOf = (w: ReturnType<typeof mountRow>) => w.findAll('[data-test="label-badge"]').map((b) => b.text())
  beforeEach(() => {
    useLabelsStore(pinia).labels = [1, 2, 3, 4].map((id) => makeLabel({ id, slug: `et${id}` }))
  })

  it('a lista normal mostra até 3 etiquetas e soma o resto', () => {
    const w = mountRow(makeSession({ label_ids: [1, 2, 3, 4] }))
    expect(labelsOf(w)).toEqual(['et1', 'et2', 'et3'])
    expect(w.get('[data-test="label-more"]').text()).toBe('+1')
  })

  it('a variante inbox também mostra, ao lado do título', () => {
    const w = mountRow(makeSession({ label_ids: [2] }), 'inbox')
    expect(labelsOf(w)).toEqual(['et2'])
    expect(w.get('[data-test="row-title"]').find('[data-test="label-badges"]').exists()).toBe(true)
    expect(w.get('[data-test="row-title"]').classes()).toContain('overflow-hidden')
  })

  it('sem etiquetas não mostra nada', () => {
    expect(mountRow(makeSession({ label_ids: [] })).find('[data-test="label-badges"]').exists()).toBe(false)
    expect(mountRow(makeSession()).find('[data-test="label-badges"]').exists()).toBe(false)
  })
})

describe('selo de agente na linha', () => {
  it('sessão de agente mostra "Agente · nome"', () => {
    useOrgStore(pinia).agents = [makeAgent({ id: 4, name: 'Triagem' })]
    const w = mountRow(makeSession({ agent_id: 4 }))
    expect(w.get('[data-test="row-title"]').get('[data-test="agent-badge"]').text()).toBe('Agente · Triagem')
  })

  it('agente que não está carregado mostra só "Agente"', () => {
    expect(mountRow(makeSession({ agent_id: 9 })).get('[data-test="agent-badge"]').text()).toBe('Agente')
  })

  it('sessão comum não tem o selo', () => {
    expect(mountRow(makeSession()).find('[data-test="agent-badge"]').exists()).toBe(false)
    expect(mountRow(makeSession({ agent_id: null })).find('[data-test="agent-badge"]').exists()).toBe(false)
  })
})
