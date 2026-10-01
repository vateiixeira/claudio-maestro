import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { beforeEach, describe, expect, it, vi } from 'vitest'

beforeEach(() => { localStorage.clear(); vi.resetModules() })

describe('migração antes dos demais módulos', () => {
  it('o menu lateral já nasce com o valor guardado sob o nome antigo', async () => {
    localStorage.setItem('vibing:sidebar-collapsed', '{"project":[3],"group":[5]}')

    // Same order as main.ts: the migration module first, then the rest.
    await import('../migrateStorage')
    const { collapsed } = await import('../sidebarCollapse')

    expect(collapsed.value).toEqual({ project: [3], group: [5] })
    expect(localStorage.getItem('vibing:sidebar-collapsed')).toBeNull()
  })

  it('sem a migração antes, o valor antigo seria perdido (o erro que isto evita)', async () => {
    localStorage.setItem('vibing:sidebar-collapsed', '{"project":[3],"group":[5]}')

    const { collapsed } = await import('../sidebarCollapse')

    expect(collapsed.value).toEqual({ project: [], group: [] })
  })

  it('o main.ts importa a migração antes de qualquer outro módulo', () => {
    const source = readFileSync(resolve(__dirname, '../main.ts'), 'utf8')
    const firstImport = source.split('\n').find((line) => line.startsWith('import '))
    expect(firstImport).toBe("import './migrateStorage'")
    expect(source).not.toContain('migrateLegacyStorage')
  })
})
