import { describe, expect, it } from 'vitest'
import { repoLabel, syncCounts } from '../repoLabel'
import { makeRepoDetails } from '../../test/factories'

describe('repoLabel', () => {
  it('usa o nome do projeto para a própria pasta e o caminho relativo para as outras', () => {
    expect(repoLabel(makeRepoDetails({ rel_path: '.' }), 'ecommerce-dash')).toBe('ecommerce-dash')
    expect(repoLabel(makeRepoDetails({ rel_path: 'dash-crm' }), 'ecommerce-dash')).toBe('dash-crm')
  })
})

describe('syncCounts', () => {
  it('sem upstream, indisponível, em dia e divergido', () => {
    expect(syncCounts(makeRepoDetails({ upstream: null })).kind).toBe('none')
    expect(syncCounts(makeRepoDetails({ ahead: null })).kind).toBe('unavailable')
    expect(syncCounts(makeRepoDetails({ ahead: 0, behind: 0 })).kind).toBe('synced')
    expect(syncCounts(makeRepoDetails({ ahead: 3, behind: 1 }))).toEqual({ kind: 'diverged', ahead: 3, behind: 1 })
  })
})
