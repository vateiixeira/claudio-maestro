/** Where a context menu opens: the pointer, or the element's bottom-left corner when the keyboard (Shift+F10, menu key) sent 0,0. */
export function contextPoint(event: MouseEvent): { x: number; y: number } {
  if (event.clientX === 0 && event.clientY === 0 && event.currentTarget instanceof Element) {
    const box = event.currentTarget.getBoundingClientRect()
    return { x: box.left, y: box.bottom }
  }
  return { x: event.clientX, y: event.clientY }
}
