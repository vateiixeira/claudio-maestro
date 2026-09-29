// Images attached to a message: same limits as the backend.

export const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp']
export const MAX_IMAGE_BYTES = 5 * 1024 * 1024
export const MAX_IMAGES = 10

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

/** Image files of a paste or drop. */
export function filesFrom(transfer: { files?: ArrayLike<File> | null } | null | undefined): File[] {
  return Array.from(transfer?.files ?? [])
}
