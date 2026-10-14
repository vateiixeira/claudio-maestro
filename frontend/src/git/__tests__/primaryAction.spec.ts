import { describe, expect, it } from 'vitest'
import { primaryAction, publishRemote } from '../primaryAction'
import { makeRepoDetails, makeRepoState } from '../../test/factories'
import type { RepoFile } from '../../types/api'

const file = (path: string, status: RepoFile['status']): RepoFile => ({ path, status, kind: 'M', added: 1, removed: 0 })

describe('primaryAction', () => {
  it('em merge com conflito: Concluir merge desligado com a contagem', () => {
    const repo = makeRepoDetails({ state: makeRepoState({ merging: true, conflicts: ['a', 'b'] }), files: [file('a', 'conflict'), file('b', 'conflict')] })
    expect(primaryAction(repo, 'msg')).toMatchObject({ kind: 'merge-continue', label: 'Concluir merge (falta resolver 2)', disabled: true })
  })

  it('em merge sem conflito: Concluir merge, desligado sem mensagem', () => {
    const repo = makeRepoDetails({ state: makeRepoState({ merging: true }) })
    expect(primaryAction(repo, 'Merge')).toMatchObject({ kind: 'merge-continue', label: 'Concluir merge', disabled: false })
    expect(primaryAction(repo, '  ').disabled).toBe(true)
  })

  it('conflito fora de um merge (rebase, cherry-pick) desliga o Commitar, com o motivo', () => {
    const repo = makeRepoDetails({ files: [file('a', 'conflict'), file('b', 'staged')] })
    expect(primaryAction(repo, 'msg')).toMatchObject({ kind: 'commit', disabled: true, reason: 'Resolva os conflitos pelo terminal' })
  })

  it('preparados contam arquivos distintos', () => {
    const repo = makeRepoDetails({ files: [file('a', 'staged'), file('a', 'unstaged'), file('b', 'staged')] })
    expect(primaryAction(repo, 'x')).toMatchObject({ kind: 'commit', label: 'Commitar 2 preparados', disabled: false })
    expect(primaryAction(makeRepoDetails({ files: [file('a', 'staged')] }), 'x').label).toBe('Commitar 1 preparado')
  })

  it('alterações sem preparados: Commitar, e desligado sem mensagem', () => {
    const repo = makeRepoDetails({ files: [file('a', 'untracked')] })
    expect(primaryAction(repo, 'x')).toMatchObject({ kind: 'commit', label: 'Commitar', disabled: false })
    expect(primaryAction(repo, '')).toMatchObject({ disabled: true, reason: 'Escreva a mensagem do commit' })
  })

  it('branch sem upstream: Publicar em origin ou no único remoto', () => {
    const base = { upstream: null, ahead: null, behind: null }
    expect(primaryAction(makeRepoDetails(base), '').label).toBe('Publicar branch em origin')
    expect(primaryAction(makeRepoDetails({ ...base, state: makeRepoState({ remotes: ['fork'] }) }), '').label).toBe('Publicar branch em fork')
    const many = primaryAction(makeRepoDetails({ ...base, state: makeRepoState({ remotes: ['a', 'b'] }) }), '')
    expect(many).toMatchObject({ kind: 'publish', label: 'Publicar branch', disabled: true })
    expect(primaryAction(makeRepoDetails({ ...base, state: makeRepoState({ remotes: [] }) }), '')).toMatchObject({ label: 'Commitar', disabled: true })
  })

  it('HEAD destacado nunca oferece publicar', () => {
    const repo = makeRepoDetails({ detached: true, branch: null, upstream: null, ahead: null, behind: null })
    expect(primaryAction(repo, '')).toMatchObject({ label: 'Commitar', disabled: true })
    expect(primaryAction(makeRepoDetails({ detached: true, branch: null, upstream: null, files: [file('a', 'unstaged')] }), 'x')).toMatchObject({ label: 'Commitar', disabled: false })
  })

  it('repositório sem commits oferece Commitar', () => {
    const repo = makeRepoDetails({ head: null, head_sha: null, upstream: null, ahead: null, behind: null, files: [file('a', 'untracked')] })
    expect(primaryAction(repo, 'Primeiro')).toMatchObject({ kind: 'commit', label: 'Commitar', disabled: false })
  })

  it('sincronizar, enviar e baixar', () => {
    expect(primaryAction(makeRepoDetails({ ahead: 14, behind: 2 }), '').label).toBe('Sincronizar 2↓ 14↑')
    expect(primaryAction(makeRepoDetails({ ahead: 1, behind: 0 }), '').label).toBe('Enviar 1 commit')
    expect(primaryAction(makeRepoDetails({ ahead: 3, behind: 0 }), '').label).toBe('Enviar 3 commits')
    expect(primaryAction(makeRepoDetails({ ahead: 0, behind: 1 }), '').label).toBe('Baixar 1 commit')
    expect(primaryAction(makeRepoDetails({ ahead: 0, behind: 3 }), '').label).toBe('Baixar 3 commits')
  })

  it('driver de merge desliga baixar e sincronizar, com o motivo', () => {
    const state = makeRepoState({ no_merge: 'Este repositório tem um driver de merge próprio (npm).' })
    expect(primaryAction(makeRepoDetails({ ahead: 0, behind: 2, state }), '')).toMatchObject({ kind: 'pull', disabled: true, reason: state.no_merge })
    expect(primaryAction(makeRepoDetails({ ahead: 1, behind: 0, state }), '')).toMatchObject({ kind: 'push', disabled: false })
  })

  it('nada a fazer: Commitar desligado', () => {
    expect(primaryAction(makeRepoDetails(), 'x')).toMatchObject({ kind: 'commit', label: 'Commitar', disabled: true })
  })

  it('publishRemote', () => {
    expect(publishRemote(['fork', 'origin'])).toBe('origin')
    expect(publishRemote(['fork'])).toBe('fork')
    expect(publishRemote(['a', 'b'])).toBeNull()
    expect(publishRemote([])).toBeNull()
  })
})
