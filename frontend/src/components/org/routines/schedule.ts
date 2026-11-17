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

const pad = (n: number) => String(n).padStart(2, '0')

/** The digits of a "135"-style string that are real weekdays, sorted and without repeats. */
const validDigits = (days: string) => [...new Set(days.split('').filter((d) => DAYS.some((day) => day.digit === d)))].sort()

/** The next time of the schedules after `now`, whether or not the routine is on; null when there is none. */
export function nextSlot(schedules: ScheduleRow[], now: Date): Date | null {
  let best: Date | null = null
  for (let offset = 0; offset <= 7; offset++) {
    const day = new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset)
    const iso = String(((day.getDay() + 6) % 7) + 1)
    for (const schedule of schedules) {
      if (!schedule.days.includes(iso)) continue
      const [h, m] = schedule.time.split(':').map(Number)
      const at = new Date(day.getFullYear(), day.getMonth(), day.getDate(), h ?? 0, m ?? 0)
      if (at.getTime() > now.getTime() && (!best || at.getTime() < best.getTime())) best = at
    }
    if (best) break
  }
  return best
}

/** "hoje 18:40", "amanhã 08:40" or "sex 08:40". */
export function slotLabel(at: Date, now: Date): string {
  const time = `${pad(at.getHours())}:${pad(at.getMinutes())}`
  const startOf = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const diff = Math.round((startOf(at) - startOf(now)) / 86_400_000)
  if (diff === 0) return `hoje ${time}`
  if (diff === 1) return `amanhã ${time}`
  return `${DAYS[(at.getDay() + 6) % 7]!.short} ${time}`
}

/** "todos os dias", "de segunda a sexta", "segunda, quarta e sexta", "sábado e domingo". */
function daysPhrase(digits: string[]): string {
  if (digits.length === 7) return 'todos os dias'
  const name = (digit: string) => DAYS[Number(digit) - 1]!.name
  const first = Number(digits[0])
  const last = Number(digits[digits.length - 1])
  if (digits.length >= 3 && last - first + 1 === digits.length) return `de ${name(digits[0]!)} a ${name(digits[digits.length - 1]!)}`
  const names = digits.map(name)
  if (names.length === 1) return names[0]!
  return `${names.slice(0, -1).join(', ')} e ${names[names.length - 1]}`
}

/** The schedules in a sentence: "De segunda a sexta às 08:40; sábado e domingo às 10:00". */
export function scheduleSentence(schedules: ScheduleRow[]): string {
  const groups = new Map<string, string[]>()
  for (const schedule of schedules) {
    const key = validDigits(schedule.days).join('')
    if (!key) continue
    const times = groups.get(key) ?? []
    if (!times.includes(schedule.time)) times.push(schedule.time)
    groups.set(key, times)
  }
  if (groups.size === 0) return 'Sem horário'
  const parts = [...groups].map(([key, times]) => {
    const at = [...times].sort().map((t) => `às ${t}`)
    const when = at.length === 1 ? at[0]! : `${at.slice(0, -1).join(', ')} e ${at[at.length - 1]}`
    return `${daysPhrase(key.split(''))} ${when}`
  })
  const sentence = parts.join('; ')
  return sentence.charAt(0).toUpperCase() + sentence.slice(1)
}

/** Seven lists of times, index 0 = Monday, sorted and without repeats. */
export function weekSlots(schedules: ScheduleRow[]): string[][] {
  const week: string[][] = Array.from({ length: 7 }, () => [])
  for (const schedule of schedules) {
    for (const digit of validDigits(schedule.days)) {
      const list = week[Number(digit) - 1]!
      if (!list.includes(schedule.time)) list.push(schedule.time)
    }
  }
  return week.map((list) => list.sort())
}
