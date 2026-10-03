import { describe, expect, it } from 'vitest'
import { parsePlan, parseSteps } from '../parseSteps'

// Mirrors backend/tests/test_plans.py (parse_plan). Built at runtime so this file has no nested fence.
const FENCE = '`'.repeat(3)

const PLAN = `# Nova navegação — plano

## Restrições

- [ ] isto não é tarefa

### Tarefa 1: Resumo da sessão

- [x] **Step 1: teste**
- [x] **Step 2: código**

### Tarefa 2: Rotas

  - [X] passo recuado
  - [ ] passo aberto

### Task 3: English heading

- [ ] step

${FENCE}markdown
### Tarefa 99: exemplo dentro de bloco
- [ ] caixa de exemplo
${FENCE}

### Tarefa 4: Sem caixas

Só texto.
`

describe('parsePlan (espelha parse_plan do backend)', () => {
  it('conta tarefas, concluídas e a atual', () => {
    const plan = parsePlan(PLAN, 'fallback')!
    expect(plan.title).toBe('Nova navegação — plano')
    expect(plan.tasks.map((t) => [t.number, t.title, t.done])).toEqual([
      [1, 'Resumo da sessão', true],
      [2, 'Rotas', false],
      [3, 'English heading', false],
      [4, 'Sem caixas', false],
    ])
  })

  it('ignora blocos de código', () => {
    expect(parsePlan(PLAN, 'f')!.tasks.map((t) => t.number)).not.toContain(99)
  })

  it('sem tarefas não é plano', () => {
    expect(parsePlan('# Só um documento\n\n- [ ] item\n', 'x')).toBeNull()
  })

  it('usa o título de reserva', () => {
    expect(parsePlan('### Tarefa 1: A\n- [ ] a\n', 'meu-plano')!.title).toBe('meu-plano')
  })

  it.each([
    '### Tarefa 1: A', '### Tarefa 1. A', '### Tarefa 1 - A', '### Tarefa 1 – A',
    '### Tarefa 1 — A', '### Tarefa 1 A', '### Task 1: A', '### Tarefa 1:A', '### TAREFA 1: A',
  ])('aceita qualquer separador ou nenhum: %s', (heading) => {
    const plan = parsePlan(`# P\n${heading}\n- [ ] a\n`, 'p')!
    expect(plan.tasks.map((t) => [t.number, t.title])).toEqual([[1, 'A']])
  })

  it.each(['### Tarefa 3', '### Tarefa 3:', '### Task 3 —', '### Tarefa 3.  '])(
    'cabeçalho sem título leva o nome do número: %s',
    (heading) => {
      const plan = parsePlan(`# P\n${heading}\n- [ ] a\n`, 'p')!
      expect(plan.tasks.map((t) => [t.number, t.title])).toEqual([[3, 'Tarefa 3']])
    },
  )

  it('cabeçalho que só começa com "Tarefa" não é tarefa', () => {
    expect(parsePlan('# P\n### Tarefas pendentes\n- [ ] a\n', 'p')).toBeNull()
    expect(parsePlan('# P\n### Tarefa 1a: x\n- [ ] a\n', 'p')).toBeNull()
  })

  it('título de nível 1 depois da primeira tarefa não vira título', () => {
    const text = '### Tarefa 1: A\n- [ ] a\n# Apêndice\n- [x] solta\n### Tarefa 2: B\n- [x] b\n'
    const plan = parsePlan(text, 'arquivo')!
    expect(plan.title).toBe('arquivo')
    expect(plan.tasks.map((t) => [t.number, t.done])).toEqual([[1, false], [2, true]])
  })

  it('título antes da primeira tarefa vale', () => {
    expect(parsePlan('# Meu plano\n\ntexto\n### Tarefa 1: A\n- [ ] a\n# Apêndice\n', 'arquivo')!.title).toBe('Meu plano')
  })

  it('apêndice não toma as caixas da tarefa anterior', () => {
    const plan = parsePlan('# P\n### Tarefa 1: A\n- [x] a\n# Apêndice\n- [ ] aberta\n', 'p')!
    expect(plan.tasks[0]!.done).toBe(true)
  })

  it('aceita fim de linha CRLF', () => {
    const plan = parsePlan('# P\r\n### Tarefa 1: A\r\n- [x] a\r\n', 'p')!
    expect(plan.tasks.map((t) => [t.number, t.title, t.done])).toEqual([[1, 'A', true]])
  })
})

describe('parseSteps', () => {
  it('devolve número e título de cada passo', () => {
    expect(parseSteps(PLAN)).toEqual([
      { number: 1, title: 'Resumo da sessão' },
      { number: 2, title: 'Rotas' },
      { number: 3, title: 'English heading' },
      { number: 4, title: 'Sem caixas' },
    ])
  })

  it('devolve lista vazia quando não reconhece passos', () => {
    expect(parseSteps('# Plano\n\n1. **Criar** tabela\n')).toEqual([])
    expect(parseSteps('')).toEqual([])
  })
})
