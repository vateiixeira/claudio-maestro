export class FakeRecognition {
  static last: FakeRecognition | null = null
  lang = ''
  interimResults = false
  continuous = false
  onresult: ((e: unknown) => void) | null = null
  onerror: ((e: unknown) => void) | null = null
  onend: (() => void) | null = null
  started = false
  constructor() { FakeRecognition.last = this }
  start() { this.started = true }
  stop() { this.started = false; this.onend?.() }
  abort() { this.stop() }
  emit(...parts: Array<[string, boolean]>) {
    const results = parts.map(([t, isFinal]) => Object.assign([{ transcript: t, confidence: 1 }], { isFinal }))
    this.onresult?.({ resultIndex: 0, results })
  }
}
