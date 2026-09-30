import type {
  ActivityDay,
  CommandInfo,
  FileMatch,
  SuggestionScope,
  DigestConfig,
  DigestRun,
  DigestState,
  DigestStatus,
  DirListing,
  ChangesGroup,
  DisplayState,
  FileDiff,
  FoundRepos,
  GitRepo,
  ImageInput,
  ModelInfo,
  PlanState,
  Project,
  ProjectCreate,
  ProjectGitDetails,
  ProjectPlan,
  ProjectUpdate,
  SendResult,
  Session,
  SessionDigest,
  SessionGroup,
  SessionUpdate,
} from '../types/api'
import type { PromptDecision, PromptExtra, SessionSnapshot } from '../types/conversation'

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

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

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

async function request<T>(method: Method, url: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  // Custom header required by the backend on every /api request (blocks cross-site reads).
  const headers: Record<string, string> = { 'X-Vibing': '1' }
  const init: RequestInit = { method, headers }
  if (signal) init.signal = signal
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
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

/** Opens the system folder picker; `path` is null when the user cancels. */
export function pickFolder(): Promise<{ path: string | null }> {
  return request('POST', '/api/fs/pick')
}

/** Repositories under a folder, found the way a project finds them. */
export function listRepos(path: string, signal?: AbortSignal): Promise<FoundRepos> {
  return request('GET', `/api/fs/repos?${new URLSearchParams({ path })}`, undefined, signal)
}

// Sessions

export function listSessions(projectId: number): Promise<Session[]> {
  return request('GET', `/api/projects/${projectId}/sessions`)
}

/** All sessions, optionally filtered by project and by what the user sees. */
export function listAllSessions(filter: { projectId?: number; state?: DisplayState } = {}): Promise<Session[]> {
  const params = new URLSearchParams()
  if (filter.projectId != null) params.set('project_id', String(filter.projectId))
  if (filter.state) params.set('state', filter.state)
  const query = params.toString()
  return request('GET', `/api/sessions${query ? '?' + query : ''}`)
}

/** Sessions of every project whose title, summary or first prompt match, newest first. */
export function searchSessions(q: string, limit = 50): Promise<Session[]> {
  return request('GET', `/api/sessions/search?${new URLSearchParams({ q, limit: String(limit) })}`)
}

/** Rereads the CLI history of the project and returns its sessions. */
export function syncProject(projectId: number): Promise<Session[]> {
  return request('POST', `/api/projects/${projectId}/sync`)
}

export function createSession(projectId: number, groupId: number | null = null): Promise<Session> {
  return request('POST', `/api/projects/${projectId}/sessions`, groupId != null ? { group_id: groupId } : undefined)
}

// Groups

export function listGroups(): Promise<SessionGroup[]> {
  return request('GET', '/api/groups')
}

export function createGroup(projectId: number, name: string): Promise<SessionGroup> {
  return request('POST', `/api/projects/${projectId}/groups`, { name })
}

export function renameGroup(id: number, name: string): Promise<SessionGroup> {
  return request('PATCH', `/api/groups/${id}`, { name })
}

export function deleteGroup(id: number): Promise<void> {
  return request('DELETE', `/api/groups/${id}`)
}

export function getSession(sessionId: string): Promise<SessionSnapshot> {
  return request('GET', `/api/sessions/${encodeURIComponent(sessionId)}`)
}

export function sendMessage(sessionId: string, text: string, images: ImageInput[] = []): Promise<SendResult> {
  const body = images.length ? { text, images } : { text }
  return request('POST', `/api/sessions/${encodeURIComponent(sessionId)}/messages`, body)
}

function scopeBase(scope: SuggestionScope): string {
  return 'sessionId' in scope
    ? `/api/sessions/${encodeURIComponent(scope.sessionId)}`
    : `/api/projects/${scope.projectId}`
}

/** Slash commands available in the session folder or in the project folder. */
export function listCommands(scope: SuggestionScope): Promise<CommandInfo[]> {
  return request('GET', `${scopeBase(scope)}/commands`)
}

/** Files and folders under the scope folder that match `q` (for `@` mentions). */
export function searchFiles(scope: SuggestionScope, q: string, signal?: AbortSignal): Promise<FileMatch[]> {
  return request('GET', `${scopeBase(scope)}/files?${new URLSearchParams({ q })}`, undefined, signal)
}

/** Models the agent offers (or a fixed list before the first connection). */
export function listModels(): Promise<ModelInfo[]> {
  return request('GET', '/api/models')
}

export function interruptSession(sessionId: string): Promise<void> {
  return request('POST', `/api/sessions/${encodeURIComponent(sessionId)}/interrupt`)
}

/** Stops every running subagent of the session without interrupting its main turn. */
export function stopSubagents(sessionId: string): Promise<void> {
  return request('POST', `/api/sessions/${encodeURIComponent(sessionId)}/subagents/stop`)
}

export function answerPrompt(
  sessionId: string,
  promptId: string,
  decision: PromptDecision,
  extra: PromptExtra = {},
): Promise<void> {
  return request(
    'POST',
    `/api/sessions/${encodeURIComponent(sessionId)}/prompts/${encodeURIComponent(promptId)}`,
    { decision, ...extra },
  )
}

export function updateSession(sessionId: string, changes: SessionUpdate): Promise<Session> {
  return request('PATCH', `/api/sessions/${encodeURIComponent(sessionId)}`, changes)
}

export function markSessionSeen(sessionId: string): Promise<void> {
  return request('POST', `/api/sessions/${encodeURIComponent(sessionId)}/seen`)
}

/** Marks many sessions as seen at once; unknown ids are ignored. */
export function markSessionsSeen(sessionIds: string[]): Promise<{ updated: number }> {
  return request('POST', '/api/sessions/seen', { session_ids: sessionIds })
}

/** Conversations with messages per day and project in the last `days` days. */
export function getActivity(days = 14): Promise<ActivityDay[]> {
  return request('GET', `/api/activity?days=${days}`)
}

// App state (preferences)

export function getAppState(): Promise<Record<string, unknown>> {
  return request('GET', '/api/state')
}

export function putAppState(key: string, value: unknown): Promise<unknown> {
  return request('PUT', `/api/state/${encodeURIComponent(key)}`, value)
}

// Git

export function getProjectGit(projectId: number): Promise<{ repos: GitRepo[]; limit_reached?: boolean }> {
  return request('GET', `/api/projects/${projectId}/git`)
}

/** Files and latest commits of each repository of the project. */
export function getProjectGitDetails(projectId: number, signal?: AbortSignal): Promise<ProjectGitDetails> {
  return request('GET', `/api/projects/${projectId}/git/details`, undefined, signal)
}

/** Current diff of a file against the last commit. `file` is relative to the repository. */
export function getFileDiff(projectId: number, repo: string, file: string, signal?: AbortSignal): Promise<FileDiff> {
  return request('GET', `/api/projects/${projectId}/diff?${new URLSearchParams({ repo, file })}`, undefined, signal)
}

export function getSessionChanges(sessionId: string, signal?: AbortSignal): Promise<{ repos: ChangesGroup[] }> {
  return request('GET', `/api/sessions/${encodeURIComponent(sessionId)}/changes`, undefined, signal)
}

export function openInEditor(path: string): Promise<void> {
  return request('POST', '/api/open-in-editor', { path })
}

// Plans

export function getSessionPlan(id: string): Promise<PlanState> {
  return request('GET', `/api/sessions/${encodeURIComponent(id)}/plan`)
}

export function linkSessionPlan(id: string, body: { path: string } | { auto: true }): Promise<PlanState> {
  return request('PUT', `/api/sessions/${encodeURIComponent(id)}/plan`, body)
}

export function unlinkSessionPlan(id: string): Promise<PlanState> {
  return request('DELETE', `/api/sessions/${encodeURIComponent(id)}/plan`)
}

export function listProjectPlans(projectId: number): Promise<ProjectPlan[]> {
  return request('GET', `/api/projects/${projectId}/plans`)
}

// Digest agent

export function getDigestConfig(): Promise<DigestState> {
  return request('GET', '/api/digest/config')
}

export function putDigestConfig(config: DigestConfig): Promise<DigestState> {
  return request('PUT', '/api/digest/config', config)
}

export function runDigest(): Promise<DigestStatus> {
  return request('POST', '/api/digest/run')
}

export function listDigestRuns(): Promise<DigestRun[]> {
  return request('GET', '/api/digest/runs')
}

export function getSessionDigest(id: string): Promise<SessionDigest | null> {
  return request('GET', `/api/sessions/${encodeURIComponent(id)}/digest`)
}

export function requestSessionDigest(id: string): Promise<{ queued: boolean }> {
  return request('POST', `/api/sessions/${encodeURIComponent(id)}/digest`)
}
