import { DAYS } from '../../../org'

// Helpers of the schedules of a routine. `nextFireLabel` (from `nextRunLabel`) and `toggleDay` come from `src/agents.ts` (the old agent
// screens), copied here because those screens are going away.

export interface ScheduleRow {
  /** ISO weekday digits, "1" = Monday ... "7" = Sunday. */
  days: string
  /** "HH:MM", local time. */
  time: string
}

/** Turns one weekday digit on or off in a "135"-style string, keeping the digits sorted. */
export function toggleDay(days: string, digit: string): string {
  const set = new Set(days.split('').filter(Boolean))
  if (set.has(digit)) set.delete(digit)
  else set.add(digit)
  return [...set].sort().join('')
}

/** "seg–sex" for a run of three or more days in a row, "todos os dias" for all, else the short names. */
export function daysLabel(days: string): string {
  const digits = [...new Set(days.split('').filter((d) => DAYS.some((day) => day.digit === d)))].sort()
  if (digits.length === 7) return 'todos os dias'
  const short = (digit: string) => DAYS[Number(digit) - 1]!.short
  const first = Number(digits[0])
  const last = Number(digits[digits.length - 1])
  if (digits.length >= 3 && last - first + 1 === digits.length) return `${short(digits[0]!)}–${short(digits[digits.length - 1]!)}`
  return digits.map(short).join(', ')
}

/** "seg–sex 08:00". */
export function scheduleLabel(schedule: ScheduleRow): string {
  return `${daysLabel(schedule.days)} ${schedule.time}`
}

/** The next slot of the schedules ("próximo: seg 08:40"), or why there is none. */
export function nextFireLabel(schedules: ScheduleRow[], enabled: boolean, now: Date = new Date()): string {
  if (schedules.length === 0) return 'sem horário'
  if (!enabled) return 'rotina desligada'
  let best: { at: number; iso: number; time: string } | null = null
  for (let offset = 0; offset <= 7; offset++) {
    const day = new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset)
    const iso = ((day.getDay() + 6) % 7) + 1
    for (const schedule of schedules) {
      if (!schedule.days.includes(String(iso))) continue
      const [h, m] = schedule.time.split(':').map(Number)
      const at = new Date(day.getFullYear(), day.getMonth(), day.getDate(), h ?? 0, m ?? 0).getTime()
      if (at > now.getTime() && (!best || at < best.at)) best = { at, iso, time: schedule.time }
    }
    if (best) break
  }
  if (!best) return 'sem horário'
  return `próximo: ${DAYS[best.iso - 1]!.short} ${best.time}`
}
