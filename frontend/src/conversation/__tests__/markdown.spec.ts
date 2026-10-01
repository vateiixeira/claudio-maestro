import { describe, expect, it } from 'vitest'
import { renderMarkdown } from '../markdown'

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
