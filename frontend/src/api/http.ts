import type {
  DirListing,
  Project,
  ProjectCreate,
  ProjectUpdate,
  Session,
} from '../types/api'

/** HTTP error carrying the status and the backend `detail` (already in Portuguese). */
export class ApiError extends Error {
  readonly status: number
  readonly detail: string | null

  constructor(status: number, detail: string | null, fallback: string) {
    super(detail ?? fallback)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

/** Message to show the user for any error thrown by an API call. */
export function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message
  return 'Algo deu errado. Tente de novo.'
}

type Method = 'GET' | 'POST' | 'PATCH' | 'DELETE'

// FastAPI validation errors (422) come as a list of {loc, msg}; turn them into one line.
function detailText(detail: unknown): string | null {
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail) && detail.length > 0) {
    return 'Dados inválidos: ' + detail
      .map((item) => {
        const loc = Array.isArray(item?.loc) ? item.loc.filter((p: unknown) => p !== 'body').join('.') : ''
        return loc ? `${loc} (${item?.msg ?? ''})` : String(item?.msg ?? '')
      })
      .join('; ')
  }
  return null
}

async function readDetail(response: Response): Promise<string | null> {
  try {
    const text = await response.text()
    if (!text) return null
    return detailText(JSON.parse(text)?.detail)
  } catch {
    return null
  }
}

async function request<T>(method: Method, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method }
  if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' }
    init.body = JSON.stringify(body)
  }

  let response: Response
  try {
    response = await fetch(url, init)
  } catch {
    throw new ApiError(0, null, 'Não foi possível falar com o servidor.')
  }

  if (!response.ok) {
    const detail = await readDetail(response)
    throw new ApiError(response.status, detail, `O servidor respondeu com erro ${response.status}.`)
  }
  if (response.status === 204) return undefined as T
  const text = await response.text()
  return (text ? JSON.parse(text) : undefined) as T
}

// Health

export function getHealth(): Promise<{ status: string }> {
  return request('GET', '/api/health')
}

// Projects

export function listProjects(): Promise<Project[]> {
  return request('GET', '/api/projects')
}

export function createProject(input: ProjectCreate): Promise<Project> {
  return request('POST', '/api/projects', input)
}

export function updateProject(id: number, changes: ProjectUpdate): Promise<Project> {
  return request('PATCH', `/api/projects/${id}`, changes)
}

export function deleteProject(id: number): Promise<void> {
  return request('DELETE', `/api/projects/${id}`)
}

// Folder browser

export function listDirs(path?: string): Promise<DirListing> {
  const query = path ? '?' + new URLSearchParams({ path }).toString() : ''
  return request('GET', `/api/fs/dirs${query}`)
}

// Sessions

export function listSessions(projectId: number): Promise<Session[]> {
  return request('GET', `/api/projects/${projectId}/sessions`)
}

export function createSession(projectId: number): Promise<Session> {
  return request('POST', `/api/projects/${projectId}/sessions`)
}
