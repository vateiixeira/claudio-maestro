import type {
  ActivityDay,
  BranchList,
  ClaudeCliInfo,
  ClaudeCliUpdateResult,
  CommandInfo,
  CommitDetail,
  ContextDetailsResponse,
  DeliveriesDay,
  Delivery,
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
  GitOpAnswer,
  GitOpKind,
  GitRepo,
  ImageInput,
  Label,
  ModelInfo,
  MarkdownFile,
  PlanState,
  RepoLog,
  SearchResult,
  Project,
  ProjectCreate,
  ProjectGitDetails,
  ProjectPlan,
  ProjectUpdate,
  SendResult,
  Session,
  SessionClosure,
  SessionDigest,
  SessionGroup,
  SessionUpdate,
  Announcement,
  GithubSettings,
  Specialist,
  SpecialistCreate,
  SpecialistItem,
  SpecialistNotice,
  SpecialistRun,
  SpecialistUpdate,
  UpdateJob,
  UpdateState,
  UsageSnapshot,
} from '../types/api'
import type { PromptDecision, PromptExtra, SessionSnapshot } from '../types/conversation'

/** HTTP error carrying the status and the backend `detail` (already in Portuguese). */
export class ApiError extends Error {
  readonly status: number
  readonly detail: string | null
  /** The raw `detail` when the backend sent an object (for example `{code, message}`); null otherwise. */
  readonly data: Record<string, unknown> | null

  constructor(status: number, detail: string | null, fallback: string, data: Record<string, unknown> | null = null) {
    super(detail ?? fallback)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.data = data
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
  if (isRecord(detail) && typeof detail.message === 'string' && detail.message) return detail.message
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

async function readDetail(response: Response): Promise<{ text: string | null; data: Record<string, unknown> | null }> {
  try {
    const body = await response.text()
    if (!body) return { text: null, data: null }
    const detail = JSON.parse(body)?.detail
    return { text: detailText(detail), data: isRecord(detail) ? detail : null }
  } catch {
    return { text: null, data: null }
  }
}

export async function request<T>(method: Method, url: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  // Custom header required by the backend on every /api request (blocks cross-site reads).
  const headers: Record<string, string> = { 'X-Maestro': '1' }
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
    const { text, data } = await readDetail(response)
    throw new ApiError(response.status, text, `O servidor respondeu com erro ${response.status}.`, data)
  }
  if (response.status === 204) return undefined as T
  const text = await response.text()
  return (text ? JSON.parse(text) : undefined) as T
}

// Health

export function getHealth(): Promise<{ status: string }> {
  return request('GET', '/api/health')
}

// Updates

export function getUpdates(): Promise<UpdateState> {
  return request('GET', '/api/updates')
}

export function applyUpdate(version: string, confirmSessionsDrop = false): Promise<{ job: UpdateJob | null }> {
  return request('POST', '/api/updates/apply', { version, confirm_sessions_drop: confirmSessionsDrop })
}

export function restartAgentd(): Promise<{ restarted: boolean }> {
  return request('POST', '/api/agentd/restart')
}

// Claude CLI

export function getClaudeCli(): Promise<ClaudeCliInfo> {
  return request('GET', '/api/claude-cli')
}

export function updateClaudeCli(): Promise<ClaudeCliUpdateResult> {
  return request('POST', '/api/claude-cli/update')
}

// Usage

export function getUsage(): Promise<UsageSnapshot> {
  return request('GET', '/api/usage')
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

/** Sessions of every project whose title, summary, first prompt or messages match, metadata first, newest first. */
export function searchSessions(q: string, limit = 50): Promise<SearchResult[]> {
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

// Labels

export function listLabels(): Promise<Label[]> {
  return request('GET', '/api/labels')
}

export function createLabel(slug: string, color: string): Promise<Label> {
  return request('POST', '/api/labels', { slug, color })
}

export function updateLabel(id: number, changes: { slug?: string; color?: string }): Promise<Label> {
  return request('PATCH', `/api/labels/${id}`, changes)
}

export function deleteLabel(id: number): Promise<void> {
  return request('DELETE', `/api/labels/${id}`)
}

export function setSessionLabels(sessionId: string, labelIds: number[]): Promise<Session> {
  return request('PUT', `/api/sessions/${encodeURIComponent(sessionId)}/labels`, { label_ids: labelIds })
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

/** "Verificar agora": fetches the remotes of the project's repositories and returns them like GET /git. */
export function fetchProjectGit(projectId: number): Promise<{ repos: GitRepo[]; limit_reached?: boolean }> {
  return request('POST', `/api/projects/${projectId}/git/fetch`)
}

/** Files and latest commits of each repository of the project. */
export function getProjectGitDetails(projectId: number, signal?: AbortSignal): Promise<ProjectGitDetails> {
  return request('GET', `/api/projects/${projectId}/git/details`, undefined, signal)
}

/** A write action of the Git panel. `body` carries `repo` and the action's fields. */
export function gitOp(projectId: number, kind: GitOpKind, body: Record<string, unknown>): Promise<GitOpAnswer> {
  return request('POST', `/api/projects/${projectId}/git/${kind}`, body)
}

/** Current diff of a file against the last commit. `file` is relative to the repository. */
export function getFileDiff(projectId: number, repo: string, file: string, signal?: AbortSignal): Promise<FileDiff> {
  return request('GET', `/api/projects/${projectId}/diff?${new URLSearchParams({ repo, file })}`, undefined, signal)
}

/** History of a branch (null: HEAD), `limit` commits after `skip`. */
export function getRepoLog(
  projectId: number, repo: string, ref: string | null = null, skip = 0, limit?: number, signal?: AbortSignal,
): Promise<RepoLog> {
  const query = new URLSearchParams({ repo, skip: String(skip) })
  if (ref) query.set('ref', ref)
  if (limit !== undefined) query.set('limit', String(limit))
  return request('GET', `/api/projects/${projectId}/git/log?${query}`, undefined, signal)
}

export function getCommit(projectId: number, repo: string, sha: string): Promise<CommitDetail> {
  return request('GET', `/api/projects/${projectId}/git/commit?${new URLSearchParams({ repo, sha })}`)
}

/** Diff of one file of a commit against its first parent. */
export function getCommitDiff(projectId: number, repo: string, sha: string, file: string): Promise<FileDiff> {
  return request('GET', `/api/projects/${projectId}/git/commit/diff?${new URLSearchParams({ repo, sha, file })}`)
}

export function getBranches(projectId: number, repo: string): Promise<BranchList> {
  return request('GET', `/api/projects/${projectId}/git/branches?${new URLSearchParams({ repo })}`)
}

/** Commits of `ref` that HEAD does not have. */
export function compareBranch(projectId: number, repo: string, ref: string): Promise<{ incoming: number }> {
  return request('GET', `/api/projects/${projectId}/git/compare?${new URLSearchParams({ repo, ref })}`)
}

export function getSessionChanges(sessionId: string, signal?: AbortSignal): Promise<{ repos: ChangesGroup[] }> {
  return request('GET', `/api/sessions/${encodeURIComponent(sessionId)}/changes`, undefined, signal)
}

/** Context window breakdown of a session; the backend reads it from the live process (up to 10 s). */
export function getSessionContext(sessionId: string, signal?: AbortSignal): Promise<ContextDetailsResponse> {
  return request('GET', `/api/sessions/${encodeURIComponent(sessionId)}/context`, undefined, signal)
}

export function openInEditor(path: string): Promise<void> {
  return request('POST', '/api/open-in-editor', { path })
}

// Plans

export function getSessionMarkdown(id: string, path: string): Promise<MarkdownFile> {
  return request('GET', `/api/sessions/${encodeURIComponent(id)}/markdown?path=${encodeURIComponent(path)}`)
}

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

export function getSessionClosure(id: string): Promise<SessionClosure | null> {
  return request('GET', `/api/sessions/${encodeURIComponent(id)}/closure`)
}

export function resolveClosureItem(id: string, item: string): Promise<SessionClosure> {
  return request('POST', `/api/sessions/${encodeURIComponent(id)}/closure/resolve`, { item })
}

/** Three title suggestions from the model; renames nothing. */
export function suggestSessionTitles(id: string): Promise<string[]> {
  return request<{ suggestions: string[] }>('POST', `/api/sessions/${encodeURIComponent(id)}/title-suggestions`).then((r) => r.suggestions)
}

// Deliveries

export function getDeliveries(date: string): Promise<DeliveriesDay> {
  return request('GET', `/api/deliveries?date=${encodeURIComponent(date)}`)
}

export function summarizeDelivery(id: number): Promise<Delivery> {
  return request('POST', `/api/deliveries/${id}/summarize`)
}

// Terminal

/** Types a command into the session's terminal. Only a click of the user may call this. */
export function runInTerminal(sessionId: string, command: string): Promise<{ run_id: string }> {
  return request('POST', `/api/sessions/${encodeURIComponent(sessionId)}/terminal/run`, { command })
}

/** Ends the session's terminal (the shell and whatever runs in it). */
export function closeTerminal(sessionId: string): Promise<void> {
  return request('DELETE', `/api/sessions/${encodeURIComponent(sessionId)}/terminal`)
}

// Agents (specialists)

export function listSpecialists(): Promise<Specialist[]> {
  return request('GET', '/api/specialists')
}

export function createSpecialist(body: SpecialistCreate): Promise<Specialist> {
  return request('POST', '/api/specialists', body)
}

export function updateSpecialist(id: number, body: SpecialistUpdate): Promise<Specialist> {
  return request('PATCH', `/api/specialists/${id}`, body)
}

export function deleteSpecialist(id: number): Promise<void> {
  return request('DELETE', `/api/specialists/${id}`)
}

export function getSpecialistSkill(id: number): Promise<{ text: string }> {
  return request('GET', `/api/specialists/${id}/skill`)
}

export function putSpecialistSkill(id: number, text: string): Promise<{ name: string; description: string }> {
  return request('PUT', `/api/specialists/${id}/skill`, { text })
}

export function getSpecialistLearnings(id: number): Promise<{ text: string }> {
  return request('GET', `/api/specialists/${id}/learnings`)
}

export function putSpecialistLearnings(id: number, text: string): Promise<{ text: string }> {
  return request('PUT', `/api/specialists/${id}/learnings`, { text })
}

/** The names of the secrets; the backend never sends a value. */
export function getSpecialistSecrets(id: number): Promise<{ names: string[] }> {
  return request('GET', `/api/specialists/${id}/secrets`)
}

/** `null` removes the secret. */
export function putSpecialistSecrets(id: number, values: Record<string, string | null>): Promise<{ names: string[] }> {
  return request('PUT', `/api/specialists/${id}/secrets`, { values })
}

export function listSpecialistItems(id: number): Promise<SpecialistItem[]> {
  return request('GET', `/api/specialists/${id}/items`)
}

export function deleteSpecialistItem(id: number, key: string): Promise<void> {
  // The key goes in the query string, whole: it can hold slashes and dots that a path would reinterpret.
  return request('DELETE', `/api/specialists/${id}/items?key=${encodeURIComponent(key)}`)
}

export function listSpecialistRuns(id: number, limit = 50): Promise<SpecialistRun[]> {
  return request('GET', `/api/specialists/${id}/runs?limit=${limit}`)
}

export function runSpecialist(id: number, text?: string): Promise<SpecialistRun> {
  return request('POST', `/api/specialists/${id}/run`, text === undefined ? {} : { text })
}

/** The agent's main conversation, created on first use. */
export function openAgentMain(id: number): Promise<{ session_id: string }> {
  return request('POST', `/api/specialists/${id}/main`)
}

/** What the runs announced to the main conversation, newest first; `pending` keeps the ones it has not received. */
export function listAnnouncements(id: number, pending = false): Promise<Announcement[]> {
  return request('GET', pending ? `/api/specialists/${id}/announcements?pending=1` : `/api/specialists/${id}/announcements`)
}

export function getGithubSettings(): Promise<GithubSettings> {
  return request('GET', '/api/specialists/github')
}

/** The secret is only written: the answer says whether one is set, never its value. */
export function putGithubSettings(body: { login?: string; secret?: string }): Promise<GithubSettings> {
  return request('PUT', '/api/specialists/github', body)
}

export function cancelSpecialistRun(id: number, runId: number): Promise<SpecialistRun> {
  return request('POST', `/api/specialists/${id}/runs/${runId}/cancel`, {})
}

export function listSpecialistNotices(unreadOnly = false): Promise<SpecialistNotice[]> {
  return request('GET', unreadOnly ? '/api/specialist-notices?unread=true' : '/api/specialist-notices')
}

export function markSpecialistNoticesRead(ids: number[]): Promise<{ updated: number }> {
  return request('POST', '/api/specialist-notices/read', { ids })
}

export function listSpecialistConversations(id: number): Promise<import('../types/api').SpecialistConversation[]> {
  return request('GET', `/api/specialists/${id}/conversations`)
}

export function openSpecialistConversation(id: number, input: { session_id?: string; new?: boolean } = {}): Promise<{ session_id: string }> {
  return request('POST', `/api/specialists/${id}/conversations`, input)
}

export function listSpecialistMessages(id: number, sessionId: string): Promise<{ id: number; text: string }[]> {
  return request('GET', `/api/specialists/${id}/messages?session_id=${encodeURIComponent(sessionId)}`)
}
