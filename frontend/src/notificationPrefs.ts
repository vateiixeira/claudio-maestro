import { ref } from 'vue'

const KEY = 'maestro:notifications'

/** What the user wants to be told about, and how. Kept in this browser, like the text size. */
export interface NotificationPrefs {
  /** A tool asks for permission. */
  permission: boolean
  /** Claude asked a question. */
  question: boolean
  /** A plan waits for approval. */
  plan: boolean
  /** A turn ended (or stopped with an error). */
  finished: boolean
  /** A subagent failed. */
  subagentFailed: boolean
  /** Only while the app is not in the foreground. */
  onlyWhenHidden: boolean
  /** A short beep with permission, question and plan. */
  sound: boolean
}

export const DEFAULT_NOTIFICATION_PREFS: NotificationPrefs = {
  permission: true,
  question: true,
  plan: true,
  finished: false,
  subagentFailed: true,
  onlyWhenHidden: true,
  sound: false,
}

/** Saved options, or the default of each one that is missing, not a boolean, or unreadable. */
export function readNotificationPrefs(): NotificationPrefs {
  const prefs = { ...DEFAULT_NOTIFICATION_PREFS }
  try {
    const raw = localStorage.getItem(KEY)
    const saved: unknown = raw === null ? null : JSON.parse(raw)
    if (saved && typeof saved === 'object' && !Array.isArray(saved)) {
      for (const key of Object.keys(prefs) as Array<keyof NotificationPrefs>) {
        const value = (saved as Record<string, unknown>)[key]
        if (typeof value === 'boolean') prefs[key] = value
      }
    }
  } catch {
    // Without storage, or with a broken value, the defaults apply.
  }
  return prefs
}

/** Current options, shared with the Preferences screen and the notifier. */
export const notificationPrefs = ref<NotificationPrefs>(readNotificationPrefs())

/** Applies one option right away and remembers it in this browser. */
export function setNotificationPref(key: keyof NotificationPrefs, value: boolean): void {
  notificationPrefs.value = { ...notificationPrefs.value, [key]: value }
  try {
    localStorage.setItem(KEY, JSON.stringify(notificationPrefs.value))
  } catch {
    // Without storage the choice lasts only for this page.
  }
}
