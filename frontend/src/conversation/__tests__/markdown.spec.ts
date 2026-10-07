import { describe, expect, it } from 'vitest'
import { dirname, joinPath, markdownViewHref, parseMarkdownRef, renderMarkdown, slugify } from '../markdown'

describe('renderMarkdown', () => {
  it('não renderiza HTML cru', () => {
    const html = renderMarkdown('oi <script>alert(1)</script> <img src=x onerror="alert(2)">')
    expect(html).not.toContain('<script')
    expect(html).not.toContain('<img')
    expect(html).toContain('&lt;script&gt;')
  })

  it('bloqueia links javascript:', () => {
    expect(renderMarkdown('[x](javascript:alert(1))')).not.toContain('href="javascript')
  })

  it('realça blocos de código', () => {
    const html = renderMarkdown('```python\ndef f(): pass\n```')
    expect(html).toContain('hljs-keyword')
  })

  it('escapa código de linguagem desconhecida', () => {
    expect(renderMarkdown('```zzz\n<b>x</b>\n```')).toContain('&lt;b&gt;')
  })

  it('envolve bloco cercado com botão de copiar', () => {
    const el = document.createElement('div')
    el.innerHTML = renderMarkdown('```py\nx = 1\n```')
    expect(el.querySelectorAll('.code-block')).toHaveLength(1)
    const block = el.querySelector('.code-block')!
    expect(block.querySelectorAll('button[data-code-copy]')).toHaveLength(1)
    expect(block.querySelector('button')!.getAttribute('aria-label')).toBe('Copiar código')
    expect(block.querySelector('button')!.textContent).toBe('Copiar')
    expect(block.querySelector('pre')).not.toBeNull()
  })

  it('bloco sem linguagem também ganha o botão', () => {
    const el = document.createElement('div')
    el.innerHTML = renderMarkdown('```\nsó texto\n```')
    expect(el.querySelectorAll('.code-block button[data-code-copy]')).toHaveLength(1)
  })

  it('código inline não ganha botão', () => {
    const el = document.createElement('div')
    el.innerHTML = renderMarkdown('use `x` aqui')
    expect(el.querySelector('.code-block')).toBeNull()
    expect(el.querySelector('button')).toBeNull()
  })
})

function dom(html: string): HTMLElement {
  const el = document.createElement('div')
  el.innerHTML = html
  return el
}

describe('parseMarkdownRef', () => {
  it('aceita caminhos relativos, absolutos e com til', () => {
    expect(parseMarkdownRef('docs/plano.md')).toEqual({ path: 'docs/plano.md', anchor: null })
    expect(parseMarkdownRef('/home/vi/x/README.MD')).toEqual({ path: '/home/vi/x/README.MD', anchor: null })
    expect(parseMarkdownRef('~/notas.md')).toEqual({ path: '~/notas.md', anchor: null })
    expect(parseMarkdownRef('  plano.md  ')).toEqual({ path: 'plano.md', anchor: null })
  })

  it('separa a âncora e descarta a linha', () => {
    expect(parseMarkdownRef('docs/a.md#tarefa-2')).toEqual({ path: 'docs/a.md', anchor: 'tarefa-2' })
    expect(parseMarkdownRef('plano.md:12')).toEqual({ path: 'plano.md', anchor: null })
    expect(parseMarkdownRef('plano.md:12-20')).toEqual({ path: 'plano.md', anchor: null })
  })

  it('recusa o que não é caminho de .md', () => {
    for (const text of ['', 'plano.mdx', 'a.py', 'uv run a.md', 'https://x.com/a.md', 'file:///a.md', 'mailto:a.md', 'javascript:a.md', 'md']) {
      expect(parseMarkdownRef(text)).toBeNull()
    }
  })
})

describe('caminhos', () => {
  it('junta e normaliza', () => {
    expect(joinPath('/p/docs/plans', '../specs/a.md')).toBe('/p/docs/specs/a.md')
    expect(joinPath('/p/docs', './a.md')).toBe('/p/docs/a.md')
    expect(joinPath('/p/docs', '/abs/a.md')).toBe('/abs/a.md')
    expect(joinPath('/p/docs', '~/a.md')).toBe('~/a.md')
    expect(dirname('/p/docs/a.md')).toBe('/p/docs')
  })

  it('monta o endereço da página de leitura', () => {
    expect(markdownViewHref('s 1', { path: 'docs/plano ação.md', anchor: 'seção' }))
      .toBe('/sessions/s%201/ver?caminho=docs%2Fplano%20a%C3%A7%C3%A3o.md#se%C3%A7%C3%A3o')
    expect(markdownViewHref('s1', { path: 'a.md', anchor: null })).toBe('/sessions/s1/ver?caminho=a.md')
  })

  it('slugify tira acentos e pontuação', () => {
    expect(slugify('Tarefa 2: Ação & reação')).toBe('tarefa-2-acao-reacao')
  })
})

describe('links de leitura', () => {
  it('código inline .md vira link em aba nova com a sessão', () => {
    const a = dom(renderMarkdown('veja `docs/plano.md` agora', { sessionId: 's1' })).querySelector('a')!
    expect(a.getAttribute('href')).toBe('/sessions/s1/ver?caminho=docs%2Fplano.md')
    expect(a.hasAttribute('data-md-view')).toBe(true)
    expect(a.getAttribute('target')).toBe('_blank')
    expect(a.getAttribute('rel')).toBe('noopener noreferrer')
    expect(a.querySelector('code')!.textContent).toBe('docs/plano.md')
  })

  it('sem sessão nada vira link de leitura', () => {
    expect(dom(renderMarkdown('`docs/plano.md`')).querySelector('a')).toBeNull()
  })

  it('código inline que não é .md continua só código', () => {
    expect(dom(renderMarkdown('`uv run pytest`', { sessionId: 's1' })).querySelector('a')).toBeNull()
  })

  it('link markdown .md vira link de leitura, decodificando o href', () => {
    const a = dom(renderMarkdown('[o plano](docs/plano%20novo.md#fim)', { sessionId: 's1' })).querySelector('a')!
    expect(a.getAttribute('href')).toBe('/sessions/s1/ver?caminho=docs%2Fplano%20novo.md#fim')
    expect(a.hasAttribute('data-md-view')).toBe(true)
  })

  it('links externos continuam abrindo fora', () => {
    const a = dom(renderMarkdown('[x](https://x.com/a.md)', { sessionId: 's1' })).querySelector('a')!
    expect(a.getAttribute('href')).toBe('https://x.com/a.md')
    expect(a.hasAttribute('data-md-view')).toBe(false)
    expect(a.getAttribute('target')).toBe('_blank')
  })

  it('código dentro de link não gera link dentro de link', () => {
    const el = dom(renderMarkdown('[`a.md`](b.md)', { sessionId: 's1' }))
    expect(el.querySelectorAll('a')).toHaveLength(1)
    expect(el.querySelector('a')!.getAttribute('href')).toBe('/sessions/s1/ver?caminho=b.md')
  })

  it('na leitura, relativos partem da pasta do documento e abrem na mesma aba', () => {
    const el = dom(renderMarkdown('[spec](../specs/a.md) e `outro.md` e [topo](#inicio)', {
      sessionId: 's1', baseDir: '/p/docs/plans', reader: true,
    }))
    const [spec, code, top] = Array.from(el.querySelectorAll('a'))
    expect(spec!.getAttribute('href')).toBe('/sessions/s1/ver?caminho=%2Fp%2Fdocs%2Fspecs%2Fa.md')
    expect(spec!.hasAttribute('target')).toBe(false)
    expect(code!.getAttribute('href')).toBe('/sessions/s1/ver?caminho=%2Fp%2Fdocs%2Fplans%2Foutro.md')
    expect(code!.hasAttribute('target')).toBe(false)
    expect(top!.hasAttribute('target')).toBe(false)
  })

  it('na leitura os títulos ganham id', () => {
    const el = dom(renderMarkdown('# Plano\n\n## Tarefa 1: Ação\n\n## Tarefa 1: Ação', { reader: true }))
    expect(Array.from(el.querySelectorAll('h1, h2')).map((h) => h.id)).toEqual(['plano', 'tarefa-1-acao', 'tarefa-1-acao-2'])
  })

  it('fora da leitura os títulos não ganham id', () => {
    expect(dom(renderMarkdown('# Plano')).querySelector('h1')!.id).toBe('')
  })
})

describe('caixas de tarefa', () => {
  it('viram caixas desabilitadas, marcadas ou não', () => {
    const el = dom(renderMarkdown('- [ ] um\n- [x] dois\n- [X] três\n- normal'))
    const boxes = Array.from(el.querySelectorAll<HTMLInputElement>('input.task-checkbox'))
    expect(boxes.map((b) => b.checked)).toEqual([false, true, true])
    expect(boxes.every((b) => b.disabled)).toBe(true)
    expect(el.querySelectorAll('li.task-item')).toHaveLength(3)
    expect(el.querySelectorAll('li')[0]!.textContent!.trim()).toBe('um')
  })

  it('colchetes fora de lista continuam texto', () => {
    expect(dom(renderMarkdown('[ ] solto')).querySelector('input')).toBeNull()
  })
})
