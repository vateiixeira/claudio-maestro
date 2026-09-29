// Images attached to a message: same limits as the backend.

export const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp']
export const MAX_IMAGE_BYTES = 5 * 1024 * 1024
export const MAX_IMAGES = 10
/** Sum of the images of one message, decoded. */
export const MAX_TOTAL_BYTES = 30 * 1024 * 1024

export interface DraftImage {
  id: number
  name: string
  size: number
  mediaType: string
  /** `data:` URL, used for the thumbnail. */
  url: string
}

/** Base64 without the `data:` prefix, as the backend expects. */
export function base64Of(image: DraftImage): string {
  return image.url.slice(image.url.indexOf(',') + 1)
}

/** "120 KB", "1,5 MB". */
export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} MB`
}

/** Error for a file that cannot be attached, or null. */
export function imageProblem(file: File): string | null {
  if (!IMAGE_TYPES.includes(file.type)) {
    return `${file.name || 'Arquivo'}: formato não suportado. Use PNG, JPEG, GIF ou WebP.`
  }
  if (file.size > MAX_IMAGE_BYTES) return `${file.name || 'Imagem'} passa de 5 MB.`
  return null
}

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

let nextId = 1
export async function readImage(file: File): Promise<DraftImage> {
  const url = await readAsDataUrl(file)
  return {
    id: nextId++,
    name: file.name || 'Imagem colada',
    size: file.size,
    mediaType: file.type,
    url,
  }
}

/**
 * Checks format, size and count of `files` on top of the images already in `current`, reads the
 * accepted ones and pushes them into `current`. `added` is what was pushed; `error` gathers every
 * reason a file was left out, or is null. `current` may be a getter: the array is looked up again
 * after the reads, because the caller may have replaced it meanwhile (removing an image, finishing
 * a send). The limits are checked again on that array, right before the push, because another call
 * may have added images too: it never goes past them. Shared by the composer and the modal.
 */
export async function attachImages(
  source: DraftImage[] | (() => DraftImage[]),
  files: File[],
): Promise<{ added: DraftImage[]; error: string | null }> {
  const now = () => (typeof source === 'function' ? source() : source)
  let current = now()
  const problems = new Set<string>()
  const accepted: File[] = []
  let total = current.reduce((sum, i) => sum + i.size, 0)
  for (const file of files) {
    const problem = imageProblem(file)
    if (problem) problems.add(problem)
    else if (current.length + accepted.length >= MAX_IMAGES) {
      problems.add(`Até ${MAX_IMAGES} imagens por mensagem.`)
      break
    } else if (total + file.size > MAX_TOTAL_BYTES) {
      problems.add('As imagens de uma mensagem somam no máximo 30 MB.')
      break
    } else {
      accepted.push(file)
      total += file.size
    }
  }
  const results = await Promise.allSettled(accepted.map(readImage))
  // No await from here to the end: the check and the push cannot be interleaved with another call.
  current = now()
  total = current.reduce((sum, i) => sum + i.size, 0)
  const added: DraftImage[] = []
  for (const result of results) {
    if (result.status !== 'fulfilled') {
      problems.add('Não foi possível ler uma das imagens.')
    } else if (current.length >= MAX_IMAGES) {
      problems.add(`Até ${MAX_IMAGES} imagens por mensagem.`)
    } else if (total + result.value.size > MAX_TOTAL_BYTES) {
      problems.add('As imagens de uma mensagem somam no máximo 30 MB.')
    } else {
      current.push(result.value)
      added.push(result.value)
      total += result.value.size
    }
  }
  return { added, error: problems.size ? [...problems].join(' ') : null }
}

/** Image files of a paste or drop. */
export function filesFrom(transfer: { files?: ArrayLike<File> | null } | null | undefined): File[] {
  return Array.from(transfer?.files ?? [])
}
