/**
 * Port of `parse_plan` (backend/claudio_maestro/plans.py): same rules, so the app and the
 * backend recognize the same steps in a plan.
 *
 * A task starts at a `### Tarefa N: title` (or `### Task N: title`) heading, with any
 * separator (`:`, `.`, `-`, `–`, `—`) or none; an empty title means "Tarefa N". It runs until
 * the next heading of level 1 to 3. It is done when it has at least one checkbox and all are
 * checked. Fenced code blocks are ignored.
 */

export interface PlanTask {
  number: number
  title: string
  done: boolean
}

export interface ParsedPlan {
  title: string
  tasks: PlanTask[]
}

/** A step the user can comment on. */
export interface PlanStep {
  number: number
  title: string
}

const TASK = /^###\s+(?:Tarefa|Task)\s+(\d+)(?![\p{L}\p{N}_])\s*[:.\-–—]?\s*(.*?)\s*$/iu
const HEADING = /^(#{1,3})\s+\S/
const TITLE = /^#\s+(.+?)\s*$/
const BOX = /^\s*[-*]\s+\[([ xX])\]/
const FENCE = /^\s*(```|~~~)/
// Same line boundaries as Python's `str.splitlines()`.
const LINE_BREAK = new RegExp(String.raw`\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]`)

export function parsePlan(text: string, fallbackTitle: string): ParsedPlan | null {
  let title: string | null = null
  const tasks: PlanTask[] = []
  let number: number | null = null
  let taskTitle = ''
  let boxes = 0
  let checked = 0
  let inFence = false

  const close = () => {
    if (number !== null) tasks.push({ number, title: taskTitle, done: boxes > 0 && boxes === checked })
  }

  for (const line of text.split(LINE_BREAK)) {
    if (FENCE.test(line)) {
      inFence = !inFence
      continue
    }
    if (inFence) continue
    let match: RegExpMatchArray | null
    if (title === null && tasks.length === 0 && number === null && (match = TITLE.exec(line))) {
      title = match[1]!
      continue
    }
    if ((match = TASK.exec(line))) {
      close()
      number = Number(match[1])
      taskTitle = match[2] || `Tarefa ${number}`
      boxes = checked = 0
      continue
    }
    if (HEADING.test(line)) {
      close()
      number = null
      continue
    }
    if (number !== null && (match = BOX.exec(line))) {
      boxes += 1
      if (match[1] !== ' ') checked += 1
    }
  }
  close()
  if (tasks.length === 0) return null
  return { title: title ?? fallbackTitle, tasks }
}

/** The steps of a plan's markdown; empty when it has none the backend would recognize. */
export function parseSteps(text: string): PlanStep[] {
  return (parsePlan(text, '')?.tasks ?? []).map(({ number, title }) => ({ number, title }))
}
