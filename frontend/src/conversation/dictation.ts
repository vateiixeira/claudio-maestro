import { onBeforeUnmount, ref } from 'vue'

// Minimal typing of the Web Speech API (not in the DOM lib of every TypeScript version).
interface RecognitionResultList {
  length: number
  [index: number]: { 0: { transcript: string }; isFinal: boolean } | undefined
}
interface Recognition {
  lang: string
  interimResults: boolean
  continuous: boolean
  onresult: ((event: { results: RecognitionResultList }) => void) | null
  onerror: ((event: { error: string }) => void) | null
  onend: (() => void) | null
  start(): void
  stop(): void
  abort(): void
}
type RecognitionCtor = new () => Recognition

function recognitionCtor(): RecognitionCtor | null {
  const w = window as unknown as Record<string, unknown>
  return ((w.SpeechRecognition ?? w.webkitSpeechRecognition) as RecognitionCtor | undefined) ?? null
}

/** Target the dictation writes into: where the cursor was when it started. */
export interface DictationTarget {
  /** Called once when recording starts; returns the text and the cursor position. */
  begin(): { text: string; cursor: number }
  /** Called with the full text and the cursor after each result. */
  update(text: string, cursor: number): void
}

/**
 * Browser speech-to-text in Portuguese. The message is never sent by itself: the text
 * stays in the field. Chrome sends the audio to its speech recognition service.
 */
export function useDictation(target: DictationTarget) {
  const Ctor = recognitionCtor()
  const supported = Ctor !== null
  const recording = ref(false)
  const error = ref<string | null>(null)
  let recognition: Recognition | null = null

  function start() {
    if (!Ctor || recording.value) return
    const { text, cursor } = target.begin()
    let before = text.slice(0, cursor)
    const after = text.slice(cursor)
    if (before && !/\s$/.test(before)) before += ' '
    const joiner = after && !/^\s/.test(after) ? ' ' : ''

    const rec = new Ctor()
    rec.lang = 'pt-BR'
    rec.interimResults = true
    rec.continuous = true
    rec.onresult = (event) => {
      if (recognition !== rec) return
      let spoken = ''
      for (let i = 0; i < event.results.length; i++) spoken += event.results[i]?.[0].transcript ?? ''
      spoken = spoken.trim()
      const middle = spoken ? spoken + joiner : ''
      target.update(before + middle + after, before.length + middle.length)
    }
    rec.onerror = (event) => {
      error.value = event.error === 'not-allowed' || event.error === 'service-not-allowed'
        ? 'Sem permissão para usar o microfone. Libere o acesso no navegador e tente de novo.'
        : event.error === 'no-speech'
          ? 'Nenhuma fala detectada.'
          : event.error === 'audio-capture'
            ? 'Nenhum microfone encontrado.'
            : event.error === 'network'
              ? 'Sem conexão para o ditado.'
          : `O ditado parou (${event.error}).`
    }
    rec.onend = () => {
      recording.value = false
      if (recognition === rec) recognition = null
    }
    error.value = null
    recognition = rec
    recording.value = true
    try {
      rec.start()
    } catch {
      recording.value = false
      recognition = null
      error.value = 'Não foi possível iniciar o ditado.'
    }
  }

  // Detaches before aborting: a late result must not write into the field again.
  function stop() {
    const rec = recognition
    recognition = null
    recording.value = false
    if (!rec) return
    rec.onresult = null
    rec.onerror = null
    rec.onend = null
    rec.abort()
  }

  function toggle() {
    if (recording.value) stop()
    else start()
  }

  onBeforeUnmount(stop)

  return { supported, recording, error, toggle, stop }
}
