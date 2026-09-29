import { reactive } from 'vue'
import type { UserItem } from '../types/conversation'

// Previews of images sent from this tab. The backend keeps only their type and size,
// so the thumbnails live here until the page reloads or the column closes.

export interface SentImage {
  url: string
  mediaType: string
  size: number
}

const pending = new Map<string, SentImage[][]>()
const byItem = reactive(new Map<string, { sessionId: string; urls: string[] }>())

/** Called right before sending; returns a function that drops the entry if sending fails. */
export function rememberSentImages(sessionId: string, images: SentImage[]): () => void {
  const queue = pending.get(sessionId) ?? []
  queue.push(images)
  pending.set(sessionId, queue)
  return () => {
    const index = queue.indexOf(images)
    if (index >= 0) queue.splice(index, 1)
  }
}

// Same images in the same order: type and size of each one.
function matches(sent: SentImage[], item: UserItem): boolean {
  const images = item.images ?? []
  return images.length === sent.length &&
    images.every((a, i) => a.type === 'image' && a.media_type === sent[i]!.mediaType && a.size === sent[i]!.size)
}

/** Links pending previews to the user item created by that send (not one from the CLI). */
export function claimLocalImages(sessionId: string, item: UserItem): void {
  if (!item.images?.length || byItem.has(item.id)) return
  const queue = pending.get(sessionId)
  const index = queue?.findIndex((sent) => matches(sent, item)) ?? -1
  if (!queue || index < 0) return
  const [sent] = queue.splice(index, 1)
  byItem.set(item.id, { sessionId, urls: sent!.map((i) => i.url) })
}

export function localImagesFor(itemId: string): string[] | undefined {
  return byItem.get(itemId)?.urls
}

/** Drops the previews of a session, when its column closes. */
export function forgetSessionImages(sessionId: string): void {
  pending.delete(sessionId)
  for (const [id, entry] of byItem) if (entry.sessionId === sessionId) byItem.delete(id)
}

export function resetLocalImages(): void {
  pending.clear()
  byItem.clear()
}
