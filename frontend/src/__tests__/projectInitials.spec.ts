import { describe, expect, it } from 'vitest'
import { projectInitials } from '../projectInitials'

describe('projectInitials', () => {
  it.each([
    ['loja-online', 'LO'],
    ['vini7-vibing', 'VV'],
    ['dash_crm', 'DC'],
    ['angular body', 'AB'],
    ['lojaOnline', 'LO'],
    ['Vibing', 'VI'],
    ['x', 'X'],
    ['ação-rápida', 'AR'],
    ['', '?'],
    ['--', '?'],
  ])('%s → %s', (name, expected) => {
    expect(projectInitials(name)).toBe(expected)
  })
})
