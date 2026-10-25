import { describe, expect, it } from 'vitest'
import { splitAnnouncements } from '../announcements'

const block = '<maestro-anuncios>\n[25/10 12:30] Rotina concluída (sessão run-1)\nAviso sem formato\n</maestro-anuncios>'

describe('anúncios na mensagem', () => {
  it('separa o bloco inicial, a data e o link da execução', () => {
    expect(splitAnnouncements(`${block}\n\nExplique o resultado`)).toEqual({
      announcements: [
        { when: '25/10 12:30', text: 'Rotina concluída', sessionId: 'run-1' },
        { when: null, text: 'Aviso sem formato', sessionId: null },
      ],
      rest: 'Explique o resultado',
    })
  })
  it('preserva blocos no meio do texto e blocos incompletos', () => {
    for (const text of [`Explique ${block}`, '<maestro-anuncios>\nIncompleto']) {
      expect(splitAnnouncements(text)).toEqual({ announcements: [], rest: text })
    }
  })
  it('não transforma conteúdo em HTML e preserva texto sem sessão', () => {
    expect(splitAnnouncements('<maestro-anuncios>\n[25/10 12:30] <script>x</script>\n</maestro-anuncios>').announcements)
      .toEqual([{ when: '25/10 12:30', text: '<script>x</script>', sessionId: null }])
  })
})
