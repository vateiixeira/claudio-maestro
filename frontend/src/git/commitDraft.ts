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
