import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, closeTerminal, createProject, deleteProject, deleteSpecialistItem, listCommands, listDirs, listProjects, runInTerminal, searchFiles, suggestSessionTitles } from '../http'

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

describe('registro dos agentes', () => {
  it('manda a chave do item na query, codificada, e não no caminho', async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)
    await deleteSpecialistItem(3, 'a/../b')
    expect(fetchMock).toHaveBeenCalledWith('/api/specialists/3/items?key=a%2F..%2Fb', expect.objectContaining({ method: 'DELETE' }))
    await deleteSpecialistItem(3, 'SENTRY 1&x=2')
    expect(fetchMock).toHaveBeenLastCalledWith('/api/specialists/3/items?key=SENTRY%201%26x%3D2', expect.objectContaining({ method: 'DELETE' }))
  })
})
