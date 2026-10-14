import { describe, expect, it } from 'vitest'
import { runningSessionIn } from '../runningSession'
import { makeSession } from '../../test/factories'

describe('runningSessionIn', () => {
  const repo = '/home/vi/dev/loja/api'
  it('acha a sessão em execução dentro do repositório', () => {
    const sessions = [
      makeSession({ session_id: 'a', cwd: '/home/vi/dev/loja/api/src', display_state: 'running' }),
      makeSession({ session_id: 'b', cwd: repo, display_state: 'waiting' }),
    ]
    expect(runningSessionIn(sessions, repo)?.session_id).toBe('a')
  })
  it('não confunde prefixo de nome', () => {
    expect(runningSessionIn([makeSession({ cwd: '/home/vi/dev/loja/api-v2', display_state: 'running' })], repo)).toBeNull()
  })
  it('conta a sessão aberta numa pasta acima do repositório, como a raiz do projeto', () => {
    const s = makeSession({ session_id: 'raiz', cwd: '/home/vi/dev/loja', display_state: 'running' })
    expect(runningSessionIn([s], repo)?.session_id).toBe('raiz')
    expect(runningSessionIn([makeSession({ cwd: '/home/vi/dev/loja/', display_state: 'running' })], repo)).not.toBeNull()
  })
  it('não conta a sessão de uma pasta vizinha', () => {
    expect(runningSessionIn([makeSession({ cwd: '/home/vi/dev/loja/web', display_state: 'running' })], repo)).toBeNull()
    expect(runningSessionIn([makeSession({ cwd: '/home/vi/dev/lo', display_state: 'running' })], repo)).toBeNull()
  })
  it('a sessão da raiz, sem worktree, conta também para as worktrees do projeto', () => {
    const s = makeSession({ session_id: 'raiz', cwd: '/home/vi/dev/loja', display_state: 'running' })
    expect(runningSessionIn([s], '/home/vi/dev/loja/.claude/worktrees/x')?.session_id).toBe('raiz')
  })
  it('prefere a sessão de dentro do repositório à da raiz', () => {
    const sessions = [
      makeSession({ session_id: 'raiz', cwd: '/home/vi/dev/loja', display_state: 'running' }),
      makeSession({ session_id: 'dentro', cwd: '/home/vi/dev/loja/api', display_state: 'running' }),
    ]
    expect(runningSessionIn(sessions, repo)?.session_id).toBe('dentro')
  })
  it('usa a worktree da sessão quando há', () => {
    const wt = '/home/vi/dev/loja/.claude/worktrees/x'
    const s = makeSession({ cwd: '/home/vi/dev/loja', worktree_path: wt, display_state: 'running' })
    expect(runningSessionIn([s], wt)?.session_id).toBe('s1')
    expect(runningSessionIn([s], '/home/vi/dev/loja')).toBeNull()
  })
})
