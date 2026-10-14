import { describe, expect, it } from 'vitest'
import { conflictPrompt } from '../conflictPrompt'
import { makeRepoDetails, makeRepoState } from '../../test/factories'

describe('conflictPrompt', () => {
  it('nomeia o repositório, as branches e os arquivos, e pede para não commitar', () => {
    const repo = makeRepoDetails({
      path: '/home/vi/dev/crm/angular-body', branch: 'develop',
      state: makeRepoState({ merging: true, merge_branch: 'feat/agente', conflicts: ['src/a.vue', 'src/b.ts'] }),
    })
    const text = conflictPrompt(repo, 'angular-body')
    expect(text).toContain('/home/vi/dev/crm/angular-body')
    expect(text).toContain('feat/agente em develop')
    expect(text).toContain('- src/a.vue\n- src/b.ts')
    expect(text).toContain('Não faça commit')
    expect(text).toContain('git add')
  })
})
