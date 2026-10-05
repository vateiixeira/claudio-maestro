import { describe, expect, it } from 'vitest'
import { behindCount, behindSrText, behindTitle, checkedAgoText, commitsText, lastSuccessText, syncState } from '../gitSync'
import { makeGitRepo } from '../test/factories'

const NOW = new Date('2026-10-05T12:00:00Z').getTime()
const ago = (minutes: number) => NOW / 1000 - minutes * 60

describe('gitSync', () => {
  it('commitsText usa singular e plural', () => {
    expect(commitsText(1)).toBe('1 commit')
    expect(commitsText(3)).toBe('3 commits')
  })

  it('behindCount é zero sem remota, sem número ou em dia', () => {
    expect(behindCount(makeGitRepo({ behind: 3 }))).toBe(3)
    expect(behindCount(makeGitRepo({ behind: null }))).toBe(0)
    expect(behindCount(makeGitRepo({ upstream: null, behind: 2 }))).toBe(0)
    expect(behindCount(makeGitRepo({ behind: 0 }))).toBe(0)
  })

  it('checkedAgoText usa o formatador de atividade; vazio quando nunca verificou', () => {
    expect(checkedAgoText(makeGitRepo({ fetched_at: ago(2) } as never), NOW)).toBe('há 2 min')
    expect(checkedAgoText(makeGitRepo({ fetched_at: null }), NOW)).toBeNull()
    expect(checkedAgoText(makeGitRepo(), NOW)).toBeNull()
  })

  it('behindTitle diz quantos commits e quando foi verificado', () => {
    const repo = makeGitRepo({ behind: 3, upstream: 'origin/main', fetched_at: ago(2) })
    expect(behindTitle(repo, NOW)).toBe('3 commits para baixar de origin/main · verificado há 2 min')
    expect(behindTitle({ ...repo, behind: 1 }, NOW)).toBe('1 commit para baixar de origin/main · verificado há 2 min')
    expect(behindTitle({ ...repo, fetched_at: null }, NOW)).toBe('3 commits para baixar de origin/main')
    expect(behindTitle({ ...repo, fetched_at: undefined }, NOW)).toBe('3 commits para baixar de origin/main')
  })

  it('behindSrText é o texto para leitor de tela', () => {
    expect(behindSrText(makeGitRepo({ behind: 3 }))).toBe('3 commits para baixar')
    expect(behindSrText(makeGitRepo({ behind: 1 }))).toBe('1 commit para baixar')
  })

  it('lastSuccessText fala da última vez com sucesso', () => {
    expect(lastSuccessText(makeGitRepo({ fetched_at: ago(40) }), NOW)).toBe('última vez há 40 min')
    expect(lastSuccessText(makeGitRepo({ fetched_at: null }), NOW)).toBeNull()
  })

  describe('syncState', () => {
    it('sem remota', () => {
      expect(syncState(makeGitRepo({ upstream: null, ahead: null, behind: null })).kind).toBe('no-upstream')
    })
    it('verificando tem prioridade sobre os números', () => {
      expect(syncState(makeGitRepo({ behind: 2, fetching: true })).kind).toBe('fetching')
    })
    it('atrás e à frente', () => {
      expect(syncState(makeGitRepo({ behind: 1, ahead: 2, upstream: 'origin/develop' }))).toEqual({ kind: 'diverged', behind: 1, ahead: 2, upstream: 'origin/develop' })
    })
    it('só atrás', () => {
      expect(syncState(makeGitRepo({ behind: 3, ahead: 0 }))).toEqual({ kind: 'behind', behind: 3, ahead: 0, upstream: 'origin/main' })
    })
    it('só à frente', () => {
      expect(syncState(makeGitRepo({ behind: 0, ahead: 2 })).kind).toBe('ahead')
    })
    it('em dia', () => {
      expect(syncState(makeGitRepo({ behind: 0, ahead: 0 })).kind).toBe('even')
    })
    it('números nulos com remota contam como em dia', () => {
      expect(syncState(makeGitRepo({ behind: null, ahead: null })).kind).toBe('even')
    })
  })
})
