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
})
