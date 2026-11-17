import { describe, expect, it } from 'vitest'
import { DEFINITION_FIELDS, fieldValue, linkLabel, memoryLevel, parseHeader, registryStatusLabel, registryTone } from '../helpers'

describe('parseHeader', () => {
  it('lê chaves, listas em linha e aspas', () => {
    expect(parseHeader('---\nname: Triagem\nmodel: opus\naddDirs: [/x/angular, "/x/pay"]\nworktree: true\n---\n# Corpo')).toEqual({
      name: 'Triagem',
      model: 'opus',
      addDirs: ['/x/angular', '/x/pay'],
      worktree: 'true',
    })
  })

  it('lê listas em bloco', () => {
    expect(parseHeader('---\nskills:\n  - revisar\n  - testar\n---\n')).toEqual({ skills: ['revisar', 'testar'] })
  })

  it('lê lista vazia', () => {
    expect(parseHeader('---\nskills: []\n---\n')).toEqual({ skills: [] })
  })

  it('tira o BOM do começo, como o backend', () => {
    expect(parseHeader('\uFEFF---\nname: Triagem\n---\n')).toEqual({ name: 'Triagem' })
  })

  it('sem cabeçalho devolve null', () => {
    expect(parseHeader('# Só corpo')).toBeNull()
  })

  it('tira aspas simples e ignora linhas que não são chave', () => {
    expect(parseHeader("---\n# comentário\nname: 'Ana'\n  aninhado: x\n---\n")).toEqual({ name: 'Ana' })
  })
})

describe('campos da definição', () => {
  it('cada campo tem o seu valor padrão', () => {
    expect(DEFINITION_FIELDS.map((f) => f.fallback)).toEqual([null, null, 'padrão', 'padrão', 'padrão: bypassPermissions', 'nenhuma', 'nenhuma', 'nenhuma', 'padrão: false', 'padrão: 120'])
  })

  it('fieldValue escreve o valor para leitura', () => {
    expect(fieldValue('addDirs', ['/x/angular', '/x/pay', '/x/crm'])).toBe('3 pastas: angular, pay, crm')
    expect(fieldValue('addDirs', ['/x/angular'])).toBe('1 pasta: angular')
    expect(fieldValue('skills', ['revisar', 'testar'])).toBe('revisar, testar')
    expect(fieldValue('skills', [])).toBe('nenhuma')
    expect(fieldValue('model', 'opus')).toBe('opus')
  })
})

describe('registro', () => {
  it('registryStatusLabel deixa a situação legível', () => {
    expect(registryStatusLabel('pr-aberto')).toBe('PR aberto')
    expect(registryStatusLabel('aguardando')).toBe('Aguardando')
    expect(registryStatusLabel('em_analise')).toBe('Em analise')
  })

  it('registryTone agrupa as situações', () => {
    expect(['aguardando', 'Pendente', 'pr-aberto', 'PR', 'aberto', 'descartado', 'ignorado', 'ruído', 'feito', 'prioridade'].map(registryTone))
      .toEqual(['waiting', 'waiting', 'info', 'info', 'info', 'muted', 'muted', 'muted', 'neutral', 'neutral'])
  })

  it('linkLabel resume o link e recusa o que não é http', () => {
    expect(linkLabel('https://github.com/exemplo/loja-demo/pull/12')).toBe('loja-demo · PR #12')
    expect(linkLabel('https://github.com/exemplo/loja-demo/issues/7')).toBe('loja-demo · #7')
    expect(linkLabel('https://www.exemplo.com/a/b')).toBe('exemplo.com')
    expect(linkLabel('javascript:alert(1)')).toBeNull()
    expect(linkLabel('/home/x/arquivo')).toBeNull()
  })
})

describe('memoryLevel', () => {
  it('ok, perto e acima do limite', () => {
    expect([3599, 3600, 4000, 4001].map((n) => memoryLevel(n, 4000))).toEqual(['ok', 'near', 'near', 'over'])
  })
})
