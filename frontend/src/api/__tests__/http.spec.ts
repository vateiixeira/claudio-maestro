import { afterEach, describe, expect, it, vi } from 'vitest'
import * as api from '../http'
import { ApiError, closeTerminal, createProject, deleteProject, listCommands, listDirs, listProjects, runInTerminal, searchFiles, suggestSessionTitles } from '../http'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => vi.unstubAllGlobals())

describe('cliente REST', () => {
  it('devolve o corpo em caso de sucesso', async () => {
    const project = {
      id: 1,
      name: 'loja',
      path: '/home/vi/dev/loja',
      color: '#B28CFF',
      position: 0,
      created_at: 1,
      available: true,
    }
    const fetchMock = vi.fn(async () => jsonResponse([project]))
    vi.stubGlobal('fetch', fetchMock)

    await expect(listProjects()).resolves.toEqual([project])
    expect(fetchMock).toHaveBeenCalledWith('/api/projects', expect.objectContaining({ method: 'GET' }))
  })

  it('envia JSON no POST', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse({ id: 2 }, 201))
    vi.stubGlobal('fetch', fetchMock)

    await createProject({ name: 'a', path: '/home/vi/a', color: '#4FD1C5' })

    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('/api/projects')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(init?.body as string)).toEqual({ name: 'a', path: '/home/vi/a', color: '#4FD1C5' })
    expect(new Headers(init?.headers).get('Content-Type')).toBe('application/json')
    expect(new Headers(init?.headers).get('X-Maestro')).toBe('1')
  })

  it('envia o cabeçalho X-Maestro também no GET', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse([]))
    vi.stubGlobal('fetch', fetchMock)
    await listProjects()
    expect(new Headers(fetchMock.mock.calls[0]![1]?.headers).get('X-Maestro')).toBe('1')
  })

  it('codifica o caminho ao listar pastas', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ path: '/home/vi/a b', parent: '/home/vi', entries: [] }))
    vi.stubGlobal('fetch', fetchMock)

    await listDirs('/home/vi/a b')
    expect(fetchMock).toHaveBeenCalledWith('/api/fs/dirs?path=%2Fhome%2Fvi%2Fa+b', expect.anything())

    await listDirs()
    expect(fetchMock).toHaveBeenLastCalledWith('/api/fs/dirs', expect.anything())
  })

  it('aceita 204 sem corpo', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 204 })))
    await expect(deleteProject(3)).resolves.toBeUndefined()
  })

  it('lança ApiError com o detail do backend', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ detail: 'Esta pasta já é usada por outro projeto.' }, 409)),
    )

    const error = await createProject({ name: 'a', path: '/x', color: '#B28CFF' }).catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(409)
    expect(error.detail).toBe('Esta pasta já é usada por outro projeto.')
    expect(error.message).toBe('Esta pasta já é usada por outro projeto.')
  })

  it('lança ApiError com o detail estruturado, usando a message como texto', async () => {
    const detail = { code: 'sessions_drop', sessions: 2, message: '2 sessões em andamento serão encerradas; confirme para continuar' }
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail }, 409)))

    const error = await createProject({ name: 'a', path: '/x', color: '#B28CFF' }).catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(409)
    expect(error.detail).toBe(detail.message)
    expect(error.message).toBe(detail.message)
    expect(error.data).toEqual(detail)
  })

  it('lança ApiError com mensagem genérica quando o erro não tem corpo', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 500 })))

    const error = await listProjects().catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(500)
    expect(error.detail).toBeNull()
    expect(error.message).toContain('500')
  })

  it('resume erros de validação 422 em texto', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({ detail: [{ loc: ['body', 'color'], msg: 'String should match pattern' }] }, 422),
      ),
    )

    const error = await createProject({ name: 'a', path: '/x', color: 'x' }).catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(422)
    expect(typeof error.message).toBe('string')
    expect(error.message.length).toBeGreaterThan(0)
  })

  it('lança ApiError com status 0 quando a rede falha', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))

    const error = await listProjects().catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(0)
    expect(error.message).toBe('Não foi possível falar com o servidor.')
  })
})

describe('sugestões', () => {
  it('monta as URLs de comandos e arquivos para sessão e para projeto', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse([]))
    vi.stubGlobal('fetch', fetchMock)

    await listCommands({ sessionId: 'a/b' })
    await listCommands({ projectId: 3 })
    const signal = new AbortController().signal
    await searchFiles({ sessionId: 's1' }, 'my file&x', signal)
    await searchFiles({ projectId: 3 }, '')

    const calls = fetchMock.mock.calls
    expect(calls[0]![0]).toBe('/api/sessions/a%2Fb/commands')
    expect(calls[1]![0]).toBe('/api/projects/3/commands')
    expect(calls[2]![0]).toBe('/api/sessions/s1/files?q=my+file%26x')
    expect(calls[2]![1]?.signal).toBe(signal)
    expect(calls[3]![0]).toBe('/api/projects/3/files?q=')
  })
})

describe('sugestões de título', () => {
  it('pede por POST e devolve só a lista', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse({ suggestions: ['A', 'B', 'C'] }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(suggestSessionTitles('s 1')).resolves.toEqual(['A', 'B', 'C'])

    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('/api/sessions/s%201/title-suggestions')
    expect(init?.method).toBe('POST')
    expect((init?.headers as Record<string, string>)['X-Maestro']).toBe('1')
  })
})

describe('terminal da sessão', () => {
  it('runInTerminal envia o comando por POST e devolve o run_id', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ run_id: 'r1' }, 202))
    vi.stubGlobal('fetch', fetchMock)
    await expect(runInTerminal('s1', 'ls -la')).resolves.toEqual({ run_id: 'r1' })
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/sessions/s1/terminal/run',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ command: 'ls -la' }) }),
    )
  })

  it('runInTerminal lança ApiError 409 com a mensagem do servidor', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'O terminal está ocupado.' }, 409)))
    await expect(runInTerminal('s1', 'ls')).rejects.toMatchObject({ status: 409, detail: 'O terminal está ocupado.' })
  })

  it('closeTerminal chama DELETE e aceita o 204', async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(closeTerminal('s1')).resolves.toBeUndefined()
    expect(fetchMock).toHaveBeenCalledWith('/api/sessions/s1/terminal', expect.objectContaining({ method: 'DELETE' }))
  })
})

describe('cliente da organização de agentes', () => {
  // [call, método, url, corpo esperado (undefined = sem corpo)]
  const cases: [string, () => Promise<unknown>, string, string, unknown][] = [
    ['listAgents', () => api.listAgents(), 'GET', '/api/agents', undefined],
    ['listAgents(projeto)', () => api.listAgents(3), 'GET', '/api/agents?project_id=3', undefined],
    ['createAgent', () => api.createAgent({ name: 'Ana', slug: 'ana', project_id: 1, kind: 'cto' }), 'POST', '/api/agents', { name: 'Ana', slug: 'ana', project_id: 1, kind: 'cto' }],
    ['getAgent', () => api.getAgent(4), 'GET', '/api/agents/4', undefined],
    ['updateAgent', () => api.updateAgent(4, { reports_to: null, enabled: false }), 'PATCH', '/api/agents/4', { reports_to: null, enabled: false }],
    ['deleteAgent', () => api.deleteAgent(4), 'DELETE', '/api/agents/4', undefined],
    ['duplicateAgent', () => api.duplicateAgent(4, { project_id: 2, slug: 'copia' }), 'POST', '/api/agents/4/duplicate', { project_id: 2, slug: 'copia' }],
    ['getAgentDefinition', () => api.getAgentDefinition(4), 'GET', '/api/agents/4/definition', undefined],
    ['putAgentDefinition', () => api.putAgentDefinition(4, { text: 'x', hash: 'h' }), 'PUT', '/api/agents/4/definition', { text: 'x', hash: 'h' }],
    ['getAgentMemory', () => api.getAgentMemory(4), 'GET', '/api/agents/4/memory', undefined],
    ['putAgentMemory', () => api.putAgentMemory(4, 'lembrar'), 'PUT', '/api/agents/4/memory', { text: 'lembrar' }],
    ['getAgentSecrets', () => api.getAgentSecrets(4), 'GET', '/api/agents/4/secrets', undefined],
    ['putAgentSecrets', () => api.putAgentSecrets(4, { TOKEN: 'v', VELHO: null }), 'PUT', '/api/agents/4/secrets', { values: { TOKEN: 'v', VELHO: null } }],
    ['listAgentRegistry', () => api.listAgentRegistry(4), 'GET', '/api/agents/4/registry', undefined],
    ['deleteAgentRegistryItem', () => api.deleteAgentRegistryItem(4, 'a/../b c'), 'DELETE', '/api/agents/4/registry?key=a%2F..%2Fb%20c', undefined],
    ['listAgentConversations', () => api.listAgentConversations(4), 'GET', '/api/agents/4/conversations', undefined],
    ['openAgentConversation', () => api.openAgentConversation(4, { new: true }), 'POST', '/api/agents/4/conversations', { new: true }],
    ['openAgentMain', () => api.openAgentMain(4), 'POST', '/api/agents/4/main', undefined],
    ['listAgentMessages', () => api.listAgentMessages(4, 's 1'), 'GET', '/api/agents/4/messages?session_id=s%201', undefined],
    ['listAnnouncements', () => api.listAnnouncements(4), 'GET', '/api/agents/4/announcements', undefined],
    ['listAnnouncements(pendentes)', () => api.listAnnouncements(4, true), 'GET', '/api/agents/4/announcements?pending=true', undefined],
    ['listAgentRuns', () => api.listAgentRuns(4, 20), 'GET', '/api/agents/4/runs?limit=20', undefined],
    ['wakeAgent', () => api.wakeAgent(4, 'Só os de hoje.'), 'POST', '/api/agents/4/wake', { text: 'Só os de hoje.' }],
    ['wakeAgent sem texto', () => api.wakeAgent(4), 'POST', '/api/agents/4/wake', {}],
    ['listAgentWakeups', () => api.listAgentWakeups(4), 'GET', '/api/agents/4/wakeups', undefined],
    ['cancelAgentWakeup', () => api.cancelAgentWakeup(4, 9), 'POST', '/api/agents/4/wakeups/9/cancel', {}],
    ['cancelAgentRun', () => api.cancelAgentRun(4, 9), 'POST', '/api/agents/4/runs/9/cancel', {}],
    ['listRoutines', () => api.listRoutines(), 'GET', '/api/routines', undefined],
    ['listRoutines(projeto)', () => api.listRoutines(2), 'GET', '/api/routines?project_id=2', undefined],
    ['createRoutine', () => api.createRoutine({ agent_id: 4, name: 'R', instruction: 'I' }), 'POST', '/api/routines', { agent_id: 4, name: 'R', instruction: 'I' }],
    ['updateRoutine', () => api.updateRoutine(5, { enabled: false }), 'PATCH', '/api/routines/5', { enabled: false }],
    ['deleteRoutine', () => api.deleteRoutine(5), 'DELETE', '/api/routines/5', undefined],
    ['runRoutine', () => api.runRoutine(5), 'POST', '/api/routines/5/run', {}],
    ['listAgentNotices', () => api.listAgentNotices(), 'GET', '/api/agent-notices', undefined],
    ['listAgentNotices(não lidos)', () => api.listAgentNotices(true), 'GET', '/api/agent-notices?unread=true', undefined],
    ['markAgentNoticesRead', () => api.markAgentNoticesRead([1, 2]), 'POST', '/api/agent-notices/read', { ids: [1, 2] }],
    ['getGithubSettings', () => api.getGithubSettings(), 'GET', '/api/agents-github', undefined],
    ['putGithubSettings', () => api.putGithubSettings({ login: 'vi' }), 'PUT', '/api/agents-github', { login: 'vi' }],
    ['listTasks', () => api.listTasks({}), 'GET', '/api/tasks', undefined],
    ['listTasks(filtro)', () => api.listTasks({ project_id: 1, status: ['todo', 'blocked'], assignee_agent_id: 4, limit: 10, offset: 20 }), 'GET', '/api/tasks?project_id=1&status=todo&status=blocked&assignee_agent_id=4&limit=10&offset=20', undefined],
    ['listTasks(ordem)', () => api.listTasks({ status: 'done', limit: 5, order: 'recent' }), 'GET', '/api/tasks?status=done&limit=5&order=recent', undefined],
    ['createTask', () => api.createTask({ project_id: 1, title: 'T' }), 'POST', '/api/tasks', { project_id: 1, title: 'T' }],
    ['getTask', () => api.getTask(7), 'GET', '/api/tasks/7', undefined],
    ['updateTask', () => api.updateTask(7, { expected_revision: 2, status: 'done' }), 'PATCH', '/api/tasks/7', { expected_revision: 2, status: 'done' }],
    ['commentTask', () => api.commentTask(7, 'ok'), 'POST', '/api/tasks/7/comments', { text: 'ok' }],
    ['unblockTask', () => api.unblockTask(7, 3), 'POST', '/api/tasks/7/unblock', { expected_revision: 3 }],
    ['listDecisions', () => api.listDecisions(), 'GET', '/api/decisions', undefined],
    ['listDecisions(filtro)', () => api.listDecisions({ project_id: 1, pending: true }), 'GET', '/api/decisions?project_id=1&pending=true', undefined],
    ['listDecisions(todas)', () => api.listDecisions({ pending: false }), 'GET', '/api/decisions?pending=false', undefined],
    ['answerDecision', () => api.answerDecision(8, 'Sim'), 'POST', '/api/decisions/8/answer', { answer: 'Sim' }],
  ]

  it.each(cases)('%s monta a URL certa com X-Maestro', async (_name, call, method, url, body) => {
    const fetchMock = vi.fn(async (_u: string, _init?: RequestInit) => new Response(method === 'DELETE' ? null : '{}', { status: method === 'DELETE' ? 204 : 200 }))
    vi.stubGlobal('fetch', fetchMock)
    await call()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [calledUrl, init] = fetchMock.mock.calls[0]!
    expect(calledUrl).toBe(url)
    expect(init?.method).toBe(method)
    expect(new Headers(init?.headers).get('X-Maestro')).toBe('1')
    if (body === undefined) expect(init?.body).toBeUndefined()
    else expect(JSON.parse(init?.body as string)).toEqual(body)
  })

  it('o 422 do AGENT.md traz o campo e a linha', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'O campo “model” está vazio.', field: 'model', line: 4 }, 422)))
    const error = await api.putAgentDefinition(4, { text: 'x', hash: 'h' }).catch((e) => e)
    expect(error).toBeInstanceOf(api.DefinitionInvalidError)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.message).toBe('O campo “model” está vazio.')
    expect(error.field).toBe('model')
    expect(error.line).toBe(4)
  })

  it('o 422 do AGENT.md sem linha (arquivo grande demais) vem com line nulo', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'O AGENT.md passa de 100 KB; reduza o texto.', field: null, line: null }, 422)))
    const error = await api.putAgentDefinition(4, { text: 'x' }).catch((e) => e)
    expect(error).toBeInstanceOf(api.DefinitionInvalidError)
    expect(error.line).toBeNull()
    expect(error.field).toBeNull()
  })

  it('o 409 de um hash velho continua um ApiError comum', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: 'O AGENT.md mudou desde que você o abriu. Recarregue para ver a versão atual.' }, 409)))
    const error = await api.putAgentDefinition(4, { text: 'x', hash: 'velho' }).catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).not.toBeInstanceOf(api.DefinitionInvalidError)
    expect(error.status).toBe(409)
  })

  it('um 422 de validação comum (lista) no AGENT.md não vira erro de definição', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ detail: [{ loc: ['body', 'text'], msg: 'Field required' }] }, 422)))
    const error = await api.putAgentDefinition(4, { text: 'x' }).catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).not.toBeInstanceOf(api.DefinitionInvalidError)
  })
})
