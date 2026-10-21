<script setup lang="ts">
import { computed } from 'vue'
import { NOTE_TEXT, formatDuration } from '../../conversation/terminalText'
import type { TerminalRun } from '../../types/conversation'
import BashPane from './BashPane.vue'
import WorkHeader from './WorkHeader.vue'

// A command the user ran in the session's terminal and sent to Claude: the compact Bash box
// (IN / OUT), tagged "Você" because Claude did not run it. No bubble: it sits where Claude's actions sit.
const props = defineProps<{ run: TerminalRun }>()

const failed = computed(() => props.run.exit_code !== null && props.run.exit_code !== 0)
const status = computed<'ok' | 'error' | 'idle'>(() => {
  if (props.run.exit_code === null) return 'idle'
  return props.run.exit_code === 0 ? 'ok' : 'error'
})
// "código 1 · 1,9 s"; only the time when the command has no exit code (it was still running).
const meta = computed(() => {
  const parts: string[] = []
  if (props.run.exit_code !== null) parts.push(`código ${props.run.exit_code}`)
  if (props.run.duration_ms !== null) parts.push(formatDuration(props.run.duration_ms))
  return parts.join(' · ') || undefined
})
</script>

<template>
  <div data-test="terminal-run-box" class="min-w-0 scroll-mt-14 rounded-lg outline-none">
    <div class="overflow-hidden rounded-lg border border-line bg-panel">
      <!-- The label is longer than the default column of a work header, so it takes the room it needs. -->
      <WorkHeader kind="bash" label="Rodou no terminal" tag="Você" desc="" :status="status" :meta="meta" class="[&_.cap]:w-auto" />
      <BashPane data-test="terminal-run-command" label="IN" name="Comando" copy-label="Copiar comando" :text="run.command" :preview="2" class="border-t border-line" />
      <div v-if="run.output" data-test="terminal-run-output" class="border-t border-line">
        <BashPane label="OUT" name="Saída" copy-label="Copiar saída" :text="run.output" :preview="4" :error="failed" />
      </div>
    </div>
    <p v-for="note in run.notes" :key="note" data-test="terminal-run-note" class="m-0 mt-1 text-xs text-fg-subtle">{{ NOTE_TEXT[note] }}</p>
  </div>
</template>
