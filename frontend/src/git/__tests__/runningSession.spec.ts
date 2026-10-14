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
  it('usa a worktree da sessão quando há', () => {
    const wt = '/home/vi/dev/loja/.claude/worktrees/x'
    const s = makeSession({ cwd: '/home/vi/dev/loja', worktree_path: wt, display_state: 'running' })
    expect(runningSessionIn([s], wt)?.session_id).toBe('s1')
    expect(runningSessionIn([s], '/home/vi/dev/loja')).toBeNull()
  })
})
