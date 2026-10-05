import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import DetailsPanel from '../DetailsPanel.vue'
import { createAppRouter } from '../../../router'
import { useChangesPanelStore } from '../../../stores/changesPanel'
import { useConversationStore } from '../../../stores/conversation'
import { useGitStore } from '../../../stores/git'
import { useProjectsStore } from '../../../stores/projects'
import { useSessionsStore } from '../../../stores/sessions'
import { jsonResponse, makeEvent, makeGitRepo, makeProject, makeSession, makeSnapshot, routeFetch } from '../../../test/factories'

enableAutoUnmount(afterEach)
let pinia: Pinia

const changes = {
  repos: [{
    path: '/home/vi/dev/loja-online', rel_path: '.', branch: 'main', detached: false, head: 'abc',
    files: [{ path: '/home/vi/dev/loja-online/a.py', rel_path: 'a.py', added: 3, removed: 1, uncommitted: true }],
  }],
}

beforeEach(async () => {
  pinia = createPinia()
  setActivePinia(pinia)
  const projects = useProjectsStore(pinia)
  projects.projects = [makeProject({ id: 1, name: 'loja-online' })]
  projects.loaded = true
  useGitStore(pinia).set(1, [makeGitRepo({ branch: 'main' })])
  useSessionsStore(pinia).setForProject(1, [makeSession({
    session_id: 's1', created_at: 1_790_000_000, last_activity_at: 1_790_000_100,
    context: { used_tokens: 84_000, max_tokens: 200_000, percent: 42 },
    display_state: 'waiting', state: 'idle',
  })])
})
afterEach(() => vi.unstubAllGlobals())

async function mountPanel(fetchHandlers = {}) {
  vi.stubGlobal('fetch', routeFetch({
    'GET /api/sessions/s1/changes': () => jsonResponse(changes),
    'GET /api/sessions/s1/digest': () => jsonResponse(null),
    'GET /api/sessions/s1/plan': () => jsonResponse({ link: 'auto', path: null, plan: null, tasks: [] }),
    'GET /api/sessions/s1': () => jsonResponse(makeSnapshot({ items: [
      { type: 'user', id: 'u1', text: 'um' }, { type: 'user', id: 'u2', text: 'dois' },
    ] })),
    ...fetchHandlers,
  }))
  await useConversationStore(pinia).load('s1')
  const router = createAppRouter(createMemoryHistory())
  const wrapper = mount(DetailsPanel, { props: { sessionId: 's1' }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return wrapper
}

describe('painel Detalhes', () => {
  it('separa o painel da conversa com a borda forte à esquerda', async () => {
    const wrapper = await mountPanel()

    const classes = wrapper.get('[data-test="details-panel"]').classes()
    expect(classes).toContain('border-l')
    expect(classes).toContain('border-line-strong')
    expect(classes).not.toContain('border-line')
  })

  it('a linha Plano saiu das propriedades: ficam Agrupador por último e os botões do plano na seção Plano', async () => {
    const wrapper = await mountPanel()

    const props = wrapper.find('[data-test="details-properties"]')
    expect(props.find('[data-test="prop-plan"]').exists()).toBe(false)
    const labels = props.findAll('dt').map((dt) => dt.text())
    expect(labels).not.toContain('Plano')
    expect(labels.slice(-1)).toEqual(['Agrupador'])
    expect(props.find('[data-test="prop-group"]').exists()).toBe(true)
  })

  it('divide as propriedades em sessão e ambiente, nessa ordem', async () => {
    const wrapper = await mountPanel()

    const groups = wrapper.find('[data-test="details-properties"]').findAll('dl')
    expect(groups).toHaveLength(2)
    expect(groups[0].findAll('dt').map((dt) => dt.text())).toEqual(['Estado', 'Turnos', 'Início', 'Última atividade'])
    expect(groups[1].findAll('dt').map((dt) => dt.text())).toEqual(['Projeto', 'Branch', 'Contexto', 'Agrupador'])
    expect(groups[0].find('[data-test="prop-state"]').exists()).toBe(true)
    expect(groups[1].find('[data-test="prop-group"]').exists()).toBe(true)
  })

  it('com worktree, a linha Worktree fica entre Branch e Contexto', async () => {
    useSessionsStore(pinia).setForProject(1, [makeSession({
      session_id: 's1', worktree_name: 'melhorias', worktree_path: '/p/.claude/worktrees/melhorias',
      display_state: 'waiting', state: 'idle',
    })])
    const wrapper = await mountPanel()

    const groups = wrapper.find('[data-test="details-properties"]').findAll('dl')
    expect(groups[1].findAll('dt').map((dt) => dt.text()).slice(0, 4)).toEqual(['Projeto', 'Branch', 'Worktree', 'Contexto'])
  })

  it('mostra a seção Plano compacta quando a sessão tem plano visível, com Abrir plano, Trocar plano… e Desligar no rodapé', async () => {
    const plan = { path: '/p/plan.md', title: 'Plano X', total: 8, done: 3, current: { number: 4, title: 'Quarta' } }
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', display_state: 'running', plan })])
    const wrapper = await mountPanel({
      'GET /api/sessions/s1/plan': () => jsonResponse({
        link: 'auto', path: plan.path, plan,
        tasks: [{ number: 1, title: 'Primeira', done: true }, { number: 4, title: 'Quarta', done: false }, { number: 5, title: 'Quinta', done: false }],
      }),
    })
    const section = wrapper.find('[data-test="details-plan"]')
    expect(section.exists()).toBe(true)
    expect(section.find('h3').text()).toBe('Plano')
    expect(section.find('[data-test="plan-strip"]').text()).toContain('4 de 8')
    expect(section.find('[data-test="plan-done-toggle"]').text()).toContain('1 concluída')
    expect(section.findAll('[data-test="plan-task"]').map((t) => t.attributes('data-status'))).toEqual(['current', 'queued'])
    const footer = section.find('[data-test="plan-footer"]')
    const labels = footer.findAll('button').map((b) => b.text())
    expect(labels).toEqual(expect.arrayContaining(['Abrir plano', 'Trocar plano…', 'Desligar']))
    expect(wrapper.findAll('[data-test="prop-plan"]')).toHaveLength(1)
    expect(footer.find('[data-test="prop-plan"]').text()).not.toContain('Plano X')
    const order = wrapper.findAll('[data-test="details-properties"], [data-test="details-plan"], [data-test="details-changes"]').map((e) => e.attributes('data-test'))
    expect(order).toEqual(['details-properties', 'details-plan', 'details-changes'])
  })

  // Content marked sr-only (position: absolute) inside the scrolling body must stay inside it;
  // otherwise it stretches the page and the whole window scrolls (seen on 1080p screens).
  it('o corpo rolável é o bloco de contenção do que tem posição absoluta', async () => {
    const wrapper = await mountPanel()

    const body = wrapper.find('[data-test="details-body"]')
    expect(body.classes()).toEqual(expect.arrayContaining(['overflow-y-auto', 'relative']))
  })

  it('sem plano visível, a seção Plano continua com o estado e o botão de escolher', async () => {
    const wrapper = await mountPanel()
    const section = wrapper.find('[data-test="details-plan"]')
    expect(section.exists()).toBe(true)
    expect(section.find('[data-test="plan-strip"]').exists()).toBe(false)
    expect(section.find('[data-test="prop-plan"]').text()).toContain('Nenhum')
    expect(section.text()).toContain('Escolher plano…')
  })

  it('mostra as propriedades da conversa', async () => {
    const wrapper = await mountPanel()

    expect(wrapper.find('[data-test="prop-state"]').text()).toContain('Sua vez')
    expect(wrapper.find('[data-test="prop-project"] a').attributes('href')).toBe('/projects/1')
    expect(wrapper.find('[data-test="prop-branch"]').text()).toContain('main')
    expect(wrapper.find('[data-test="prop-context"]').text()).toContain('42%')
    expect(wrapper.find('[data-test="prop-context"]').text()).toContain('84 mil')
    expect(wrapper.find('[data-test="prop-turns"]').text()).toContain('2')
  })

  it('Branch mostra o estado de sincronização de cada repositório, menos na worktree', async () => {
    useGitStore(pinia).set(1, [makeGitRepo({ behind: 3, upstream: 'origin/main' })])
    const wrapper = await mountPanel()
    expect(wrapper.find('[data-test="prop-branch"] [data-test="prop-branch-sync"]').text()).toContain('3 commits para baixar de origin/main')

    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', worktree_name: 'melhorias', git_branch: 'worktree-melhorias' })])
    const inWorktree = await mountPanel()
    expect(inWorktree.find('[data-test="prop-branch-sync"]').exists()).toBe(false)
  })

  it('Detalhes mostra a linha Worktree com o caminho na dica e o branch da sessão', async () => {
    useSessionsStore(pinia).setForProject(1, [makeSession({ session_id: 's1', worktree_name: 'melhorias', worktree_path: '/p/.claude/worktrees/melhorias', git_branch: 'worktree-melhorias' })])
    const wrapper = await mountPanel()

    const prop = wrapper.find('[data-test="prop-worktree"]')
    expect(prop.text()).toContain('melhorias')
    expect(prop.find('[title]').attributes('title')).toBe('/p/.claude/worktrees/melhorias')
    expect(wrapper.find('[data-test="prop-branch"]').text()).toContain('worktree-melhorias')
    expect(wrapper.find('[data-test="prop-branch"]').text()).not.toContain('main')
  })

  it('sem worktree, Detalhes não mostra a linha Worktree', async () => {
    const wrapper = await mountPanel()

    expect(wrapper.find('[data-test="prop-worktree"]').exists()).toBe(false)
  })

  it('lista os arquivos alterados e abre o diff de um deles', async () => {
    const wrapper = await mountPanel({
      'GET /api/projects/1/diff?repo=.&file=a.py': () => jsonResponse({ diff: '@@ -1 +1 @@\n-a\n+b\n', truncated: false }),
    })

    const file = wrapper.find('[data-test="changed-file"]')
    expect(file.text()).toContain('a.py')
    expect(file.text()).toContain('+3')
    await file.trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="details-properties"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="details-diff"]').text()).toContain('a.py')

    await wrapper.find('[data-test="diff-back"]').trigger('click')
    expect(wrapper.find('[data-test="details-properties"]').exists()).toBe(true)
  })

  it('abre o diff de uma edição pedida pela conversa', async () => {
    const wrapper = await mountPanel()
    useChangesPanelStore(pinia).open('s1', {
      type: 'tool', id: 't1', tool_use_id: 't1', name: 'Edit',
      input: { file_path: '/x/b.py', old_string: 'a', new_string: 'b' }, result: null,
    } as never)
    await flushPromises()

    expect(wrapper.find('[data-test="details-diff"]').text()).toContain('/x/b.py')
    await wrapper.find('[data-test="diff-back"]').trigger('click')
    expect(useChangesPanelStore(pinia).edit).toBeNull()
  })

  it('alarga e volta com o botão de expandir', async () => {
    const wrapper = await mountPanel({
      'GET /api/projects/1/diff?repo=.&file=a.py': () => jsonResponse({ diff: '', truncated: false }),
    })
    await wrapper.find('[data-test="changed-file"]').trigger('click')
    await flushPromises()

    const expand = wrapper.find('[data-test="diff-expand"]')
    expect(expand.find('svg').exists()).toBe(true)
    expect(expand.text()).toBe('')
    expect(wrapper.find('[data-test="diff-back"]').find('svg').exists()).toBe(true)
    expect(wrapper.find('[data-test="diff-back"]').text()).toBe('Voltar')
    await expand.trigger('click')
    expect(wrapper.find('[data-test="details-panel"]').attributes('data-wide')).toBe('true')
    await expand.trigger('click')
    expect(wrapper.find('[data-test="details-panel"]').attributes('data-wide')).toBe('false')
  })

  it('mostra o erro só na seção de alterações e tenta de novo', async () => {
    let calls = 0
    const wrapper = await mountPanel({
      'GET /api/sessions/s1/changes': () => (++calls === 1 ? jsonResponse({ detail: 'Falhou.' }, 500) : jsonResponse(changes)),
    })

    expect(wrapper.find('[data-test="changes-error"]').text()).toContain('Falhou.')
    expect(wrapper.find('[data-test="details-properties"]').exists()).toBe(true)
    await wrapper.find('[data-test="changes-retry"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="changed-file"]').exists()).toBe(true)
  })

  describe('lista de alterações da conversa', () => {
    const repo = (files: Array<{ rel: string; added: number | null; removed: number | null }>, rel_path = '.') => ({
      path: `/home/vi/dev/loja-online/${rel_path}`, rel_path, branch: 'main', detached: false, head: 'abc',
      files: files.map((f) => ({ path: `/home/vi/dev/loja-online/${f.rel}`, rel_path: f.rel, added: f.added, removed: f.removed, uncommitted: true })),
    })
    const turnResult = (seq: number) => makeEvent('turn.result', { subtype: 'success', is_error: false, duration_ms: 1, total_cost_usd: 0 }, seq)

    it('soma os arquivos de todos os repositórios no total "+N −N"', async () => {
      const wrapper = await mountPanel({
        'GET /api/sessions/s1/changes': () => jsonResponse({
          repos: [
            repo([{ rel: 'a.py', added: 3, removed: 1 }, { rel: 'b.py', added: 4, removed: 2 }]),
            repo([{ rel: 'c.py', added: null, removed: null }, { rel: 'd.py', added: 5, removed: 0 }], 'api'),
          ],
        }),
      })
      const total = wrapper.find('#changes-title').text()
      expect(total).toContain('+12')
      expect(total).toContain('−3')
    })

    it('busca a lista de novo quando um turno termina', async () => {
      let calls = 0
      const wrapper = await mountPanel({
        'GET /api/sessions/s1/changes': () => {
          calls += 1
          return jsonResponse({ repos: [repo(calls === 1 ? [{ rel: 'a.py', added: 1, removed: 0 }] : [{ rel: 'a.py', added: 1, removed: 0 }, { rel: 'novo.py', added: 7, removed: 2 }])] })
        },
      })
      expect(calls).toBe(1)
      expect(wrapper.findAll('[data-test="changed-file"]')).toHaveLength(1)

      useConversationStore(pinia).receive(turnResult(1))
      await flushPromises()
      expect(calls).toBe(2)
      expect(wrapper.findAll('[data-test="changed-file"]')).toHaveLength(2)
      expect(wrapper.find('#changes-title').text()).toContain('+8')
    })

    it('ignora a resposta mais antiga que chega depois da mais nova', async () => {
      const resolvers: Array<(r: Response) => void> = []
      let calls = 0
      const wrapper = await mountPanel({
        'GET /api/sessions/s1/changes': () => {
          calls += 1
          if (calls === 1) return jsonResponse({ repos: [repo([{ rel: 'inicial.py', added: 1, removed: 0 }])] })
          return new Promise<Response>((resolve) => { resolvers.push(resolve) }) as unknown as Response
        },
      })
      const store = useConversationStore(pinia)
      store.receive(turnResult(1))
      await flushPromises()
      store.receive(turnResult(2))
      await flushPromises()
      expect(resolvers).toHaveLength(2)

      resolvers[1]!(jsonResponse({ repos: [repo([{ rel: 'novo.py', added: 9, removed: 0 }])] }))
      await flushPromises()
      resolvers[0]!(jsonResponse({ repos: [repo([{ rel: 'velho.py', added: 2, removed: 0 }])] }))
      await flushPromises()

      const names = wrapper.findAll('[data-test="changed-file"]').map((f) => f.text())
      expect(names).toHaveLength(1)
      expect(names[0]).toContain('novo.py')
      expect(wrapper.find('#changes-title').text()).toContain('+9')
    })
  })
})
