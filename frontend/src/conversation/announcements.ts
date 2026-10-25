export interface ParsedAnnouncement {
  when: string | null
  text: string
  sessionId: string | null
}

/** Only the leading block injected by the backend is metadata; quoted blocks remain ordinary text. */
export function splitAnnouncements(text: string): { announcements: ParsedAnnouncement[]; rest: string } {
  const block = /^<maestro-anuncios>\r?\n([\s\S]*?)\r?\n<\/maestro-anuncios>(?:\r?\n){0,2}/.exec(text)
  if (!block) return { announcements: [], rest: text }
  const announcements = block[1]!.split(/\r?\n/).filter((line) => line.trim()).map((line) => {
    const dated = /^\[(\d{2}\/\d{2} \d{2}:\d{2})\] (.*)$/.exec(line)
    if (!dated) return { when: null, text: line, sessionId: null }
    const linked = /^(.*) \(sessão ([\w-]+)\)$/.exec(dated[2]!)
    return { when: dated[1]!, text: linked?.[1] ?? dated[2]!, sessionId: linked?.[2] ?? null }
  })
  return { announcements, rest: text.slice(block[0].length) }
}
