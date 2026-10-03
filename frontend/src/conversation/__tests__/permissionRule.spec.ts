import { describe, expect, it } from 'vitest'
import { describePermissionRule } from '../permissionRule'

const rule = (toolName: string, ruleContent: string | null = null) => ({ toolName, ruleContent })

describe('describePermissionRule', () => {
  it('sem sugestões não descreve nada', () => {
    expect(describePermissionRule(undefined)).toEqual([])
    expect(describePermissionRule(null)).toEqual([])
    expect(describePermissionRule([])).toEqual([])
  })

  it('addRules com allow libera a regra', () => {
    const out = describePermissionRule([
      { type: 'addRules', behavior: 'allow', destination: 'localSettings', rules: [rule('Bash', 'pnpm test:*')] },
    ])
    expect(out).toEqual([{ lead: 'Libera', chips: ['Bash(pnpm test:*)'], scope: 'neste projeto, só para você' }])
  })

  it('regra sem conteúdo mostra só o nome da ferramenta', () => {
    const out = describePermissionRule([
      { type: 'addRules', behavior: 'allow', destination: 'session', rules: [rule('Edit'), rule('Write', null)] },
    ])
    expect(out[0]!.chips).toEqual(['Edit', 'Write'])
  })

  it('deny bloqueia e ask pede confirmação', () => {
    const deny = describePermissionRule([{ type: 'addRules', behavior: 'deny', destination: 'session', rules: [rule('Bash', 'rm:*')] }])
    expect(deny[0]!.lead).toBe('Bloqueia')
    const ask = describePermissionRule([{ type: 'addRules', behavior: 'ask', destination: 'session', rules: [rule('Bash', 'git push:*')] }])
    expect(ask[0]!.lead).toBe('Pede confirmação para')
  })

  it('replaceRules descreve como addRules', () => {
    const out = describePermissionRule([
      { type: 'replaceRules', behavior: 'allow', destination: 'projectSettings', rules: [rule('Read', '/tmp/**')] },
    ])
    expect(out).toEqual([{ lead: 'Libera', chips: ['Read(/tmp/**)'], scope: 'neste projeto, para todos' }])
  })

  it('removeRules diz que remove a regra', () => {
    const out = describePermissionRule([
      { type: 'removeRules', behavior: 'allow', destination: 'userSettings', rules: [rule('Bash', 'ls')] },
    ])
    expect(out).toEqual([{ lead: 'Remove', chips: ['Bash(ls)'], scope: 'em todos os seus projetos' }])
  })

  it('setMode muda o modo, com o nome do modo em português', () => {
    const out = describePermissionRule([{ type: 'setMode', mode: 'acceptEdits', destination: 'session' }])
    expect(out).toEqual([{ lead: 'Muda o modo para Aceitar edições', chips: [], scope: 'só nesta sessão' }])
  })

  it('modo desconhecido aparece como veio', () => {
    const out = describePermissionRule([{ type: 'setMode', mode: 'futuro', destination: 'session' }])
    expect(out[0]!.lead).toBe('Muda o modo para futuro')
  })

  it('addDirectories dá acesso às pastas', () => {
    const out = describePermissionRule([
      { type: 'addDirectories', directories: ['/home/vi/a', '/home/vi/b'], destination: 'localSettings' },
    ])
    expect(out).toEqual([{ lead: 'Dá acesso a', chips: ['/home/vi/a', '/home/vi/b'], scope: 'neste projeto, só para você' }])
  })

  it('removeDirectories tira o acesso', () => {
    const out = describePermissionRule([{ type: 'removeDirectories', directories: ['/x'], destination: 'session' }])
    expect(out[0]!.lead).toBe('Tira o acesso a')
  })

  it.each([
    ['session', 'só nesta sessão'],
    ['localSettings', 'neste projeto, só para você'],
    ['projectSettings', 'neste projeto, para todos'],
    ['userSettings', 'em todos os seus projetos'],
  ])('destino %s vira "%s"', (destination, scope) => {
    const out = describePermissionRule([{ type: 'setMode', mode: 'plan', destination }])
    expect(out[0]!.scope).toBe(scope)
  })

  it('sem destino ou com destino desconhecido não diz onde vale', () => {
    expect(describePermissionRule([{ type: 'setMode', mode: 'plan' }])[0]!.scope).toBeNull()
    expect(describePermissionRule([{ type: 'setMode', mode: 'plan', destination: 'nuvem' }])[0]!.scope).toBeNull()
  })

  it('descreve várias sugestões, na ordem', () => {
    const out = describePermissionRule([
      { type: 'addRules', behavior: 'allow', destination: 'session', rules: [rule('Bash', 'ls')] },
      { type: 'setMode', mode: 'acceptEdits', destination: 'session' },
    ])
    expect(out.map((d) => d.lead)).toEqual(['Libera', 'Muda o modo para Aceitar edições'])
  })

  it('ignora entradas malformadas sem quebrar', () => {
    const out = describePermissionRule([
      null,
      'texto',
      { type: 'addRules', behavior: 'allow', destination: 'session' },
      { type: 'addRules', behavior: 'allow', destination: 'session', rules: [{ ruleContent: 'x' }, rule('Bash', 'ls')] },
      { type: 'setMode', destination: 'session' },
      { type: 'addDirectories', directories: [], destination: 'session' },
      { type: 'inventado' },
    ])
    expect(out).toEqual([{ lead: 'Libera', chips: ['Bash(ls)'], scope: 'só nesta sessão' }])
  })
})
