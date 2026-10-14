const PREFIX = 'maestro.commitDraft:'

/** Commit message typed in a repository, kept until the commit works. */
export function readDraft(repoPath: string): string {
  try {
    return localStorage.getItem(PREFIX + repoPath) ?? ''
  } catch {
    return ''
  }
}

export function writeDraft(repoPath: string, text: string): void {
  try {
    if (text) localStorage.setItem(PREFIX + repoPath, text)
    else localStorage.removeItem(PREFIX + repoPath)
  } catch {
    // Private window or blocked storage: the draft just is not kept.
  }
}

export function clearDraft(repoPath: string): void {
  writeDraft(repoPath, '')
}

const MERGE_PREFIX = 'maestro.mergeMessage:'

/** The merge message the app put in the field itself, to tell it from what the user typed. */
export function readMergeMessage(repoPath: string): string | null {
  try {
    return localStorage.getItem(MERGE_PREFIX + repoPath)
  } catch {
    return null
  }
}

export function writeMergeMessage(repoPath: string, text: string | null): void {
  try {
    if (text) localStorage.setItem(MERGE_PREFIX + repoPath, text)
    else localStorage.removeItem(MERGE_PREFIX + repoPath)
  } catch {
    // Same as the draft: without storage it is just not kept.
  }
}
