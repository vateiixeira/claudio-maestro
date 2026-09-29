export interface DiffLine {
  kind: 'context' | 'add' | 'del'
  oldNo: number | null
  newNo: number | null
  text: string
}

export interface PatchHunk {
  oldStart: number
  oldLines: number
  newStart: number
  newLines: number
  lines: string[]
}

export function diffFromPatch(hunks: PatchHunk[]): DiffLine[] {
  const out: DiffLine[] = []
  for (const hunk of hunks) {
    let oldNo = hunk.oldStart
    let newNo = hunk.newStart
    for (const raw of hunk.lines) {
      const mark = raw[0]
      const text = raw.slice(1)
      if (mark === '-') out.push({ kind: 'del', oldNo: oldNo++, newNo: null, text })
      else if (mark === '+') out.push({ kind: 'add', oldNo: null, newNo: newNo++, text })
      else if (mark === '\\') continue // "\ No newline at end of file"
      else out.push({ kind: 'context', oldNo: oldNo++, newNo: newNo++, text })
    }
  }
  return out
}

function splitLines(text: string): string[] {
  return text === '' ? [] : text.split('\n')
}

/** Line diff that keeps the common start and end; the middle is shown as removed then added. */
export function diffFromStrings(oldText: string, newText: string): DiffLine[] {
  const a = splitLines(oldText)
  const b = splitLines(newText)
  let start = 0
  while (start < a.length && start < b.length && a[start] === b[start]) start++
  let endA = a.length
  let endB = b.length
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
    endA--
    endB--
  }
  const out: DiffLine[] = []
  for (let i = 0; i < start; i++) out.push({ kind: 'context', oldNo: i + 1, newNo: i + 1, text: a[i]! })
  for (let i = start; i < endA; i++) out.push({ kind: 'del', oldNo: i + 1, newNo: null, text: a[i]! })
  for (let i = start; i < endB; i++) out.push({ kind: 'add', oldNo: null, newNo: i + 1, text: b[i]! })
  for (let i = endA; i < a.length; i++) {
    const j = i - endA + endB
    out.push({ kind: 'context', oldNo: i + 1, newNo: j + 1, text: a[i]! })
  }
  return out
}

function isHunkList(value: unknown): value is PatchHunk[] {
  return Array.isArray(value) && value.length > 0 && value.every((h) => h && Array.isArray(h.lines))
}

/** Diff lines for Edit, MultiEdit and Write, preferring the result's `structuredPatch`. */
export function toolDiff(name: string, input: Record<string, unknown>, details: Record<string, unknown> | null): DiffLine[] {
  const patch = details?.structuredPatch
  if (isHunkList(patch)) return diffFromPatch(patch)
  const str = (v: unknown) => (typeof v === 'string' ? v : '')
  if (name === 'Write') return diffFromStrings('', str(input.content))
  if (name === 'MultiEdit' && Array.isArray(input.edits)) {
    return input.edits.flatMap((e: Record<string, unknown>) => diffFromStrings(str(e?.old_string), str(e?.new_string)))
  }
  return diffFromStrings(str(input.old_string), str(input.new_string))
}

export function diffCounts(lines: DiffLine[]): { added: number; removed: number } {
  let added = 0
  let removed = 0
  for (const line of lines) {
    if (line.kind === 'add') added++
    else if (line.kind === 'del') removed++
  }
  return { added, removed }
}

/** Parses a unified diff (as `git diff` prints it) into lines, skipping file headers. */
export function diffFromUnified(text: string): DiffLine[] {
  const hunks: PatchHunk[] = []
  let current: PatchHunk | null = null
  for (const raw of text.split('\n')) {
    const header = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/.exec(raw)
    if (header) {
      current = {
        oldStart: Number(header[1]),
        oldLines: Number(header[2] ?? 1),
        newStart: Number(header[3]),
        newLines: Number(header[4] ?? 1),
        lines: [],
      }
      hunks.push(current)
    } else if (current && raw !== '' && ' +-\\'.includes(raw[0]!)) {
      current.lines.push(raw)
    }
  }
  return diffFromPatch(hunks)
}
