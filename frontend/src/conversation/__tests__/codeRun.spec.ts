import { describe, expect, it } from 'vitest'
import { SHELL_LANGS, commandFromBlock, runLabel } from '../codeRun'

describe('commandFromBlock', () => {
  it('lista as linguagens de shell', () => {
    expect(SHELL_LANGS).toEqual(['bash', 'sh', 'shell', 'zsh', 'console', 'terminal'])
  })

  it('bash devolve o código sem espaços nas pontas', () => {
    expect(commandFromBlock('bash', 'ls -la\n')).toBe('ls -la')
    expect(commandFromBlock('bash', '  echo oi  \n\n')).toBe('echo oi')
  })

  it('linguagem fora da lista não roda', () => {
    expect(commandFromBlock('python', 'print(1)\n')).toBeNull()
    expect(commandFromBlock('json', '{"a": 1}')).toBeNull()
  })

  it('console fica só com as linhas de comando, sem o prefixo', () => {
    expect(commandFromBlock('console', '$ ls\nsaida\n$ pwd\n')).toBe('ls\npwd')
  })

  it('console sem nenhuma linha com $ não roda', () => {
    expect(commandFromBlock('console', 'só saída\n')).toBeNull()
  })

  it('bash com $ ignora as linhas de saída', () => {
    expect(commandFromBlock('bash', '$ git status\nOn branch main\n')).toBe('git status')
  })

  it('sem linguagem, um comando conhecido roda', () => {
    expect(commandFromBlock('', 'git status\n')).toBe('git status')
    expect(commandFromBlock('', 'sudo systemctl restart x')).toBe('sudo systemctl restart x')
    expect(commandFromBlock('', '$ ls\nsaida')).toBe('ls')
  })

  it('sem linguagem, texto que não parece comando não roda', () => {
    expect(commandFromBlock('', '{"a": 1}')).toBeNull()
    expect(commandFromBlock('', 'só texto')).toBeNull()
    expect(commandFromBlock('', 'gitignore é um arquivo')).toBeNull()
    expect(commandFromBlock('', '')).toBeNull()
  })

  it('sem linguagem, mais de 10 linhas não vazias não roda', () => {
    const eleven = Array.from({ length: 11 }, (_, i) => `echo ${i}`).join('\n')
    expect(commandFromBlock('', eleven)).toBeNull()
    const ten = Array.from({ length: 10 }, (_, i) => `echo ${i}`).join('\n')
    expect(commandFromBlock('', ten)).toBe(ten)
  })

  it('linhas vazias não contam para o limite', () => {
    const lines = Array.from({ length: 10 }, (_, i) => `echo ${i}\n`).join('\n')
    expect(commandFromBlock('', lines)).not.toBeNull()
  })

  it('bloco de shell vazio não roda', () => {
    expect(commandFromBlock('bash', '  \n')).toBeNull()
  })
})

describe('runLabel', () => {
  it('traduz cada estado', () => {
    expect(runLabel('idle', null)).toBe('Rodar')
    expect(runLabel('starting', null)).toBe('Rodando…')
    expect(runLabel('running', null)).toBe('Rodando…')
    expect(runLabel('sent', 0)).toBe('Enviado · código 0')
    expect(runLabel('sent', 2)).toBe('Enviado · código 2')
    expect(runLabel('sent', null)).toBe('Enviado')
    expect(runLabel('interrupted', null)).toBe('Interrompido')
    expect(runLabel('failed', null)).toBe('Não foi possível enviar')
    expect(runLabel('busy', null)).toBe('O terminal está ocupado')
  })
})
