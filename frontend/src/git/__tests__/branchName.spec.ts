import { describe, expect, it } from 'vitest'
import { branchNameProblem } from '../branchName'

describe('branchNameProblem', () => {
  it('sugere hífens no lugar dos espaços', () => {
    expect(branchNameProblem('feat novo checkout')).toBe('Nome de branch não pode ter espaço. Por exemplo: feat-novo-checkout.')
    expect(branchNameProblem('  feat/novo  ')).toBeNull()
    expect(branchNameProblem('')).toBeNull()
  })
})
