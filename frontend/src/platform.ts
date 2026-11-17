/** True on macOS (and iOS), where the shortcut key is Command instead of Ctrl. */
export function isMacPlatform(): boolean {
  if (typeof navigator === 'undefined') return false
  return /mac|iphone|ipad|ipod/i.test(navigator.platform ?? '')
}
