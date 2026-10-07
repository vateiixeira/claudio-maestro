<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { renderMarkdown } from '../../conversation/markdown'
import { useUpdatesStore } from '../../stores/updates'
import type { UpdateStep } from '../../types/api'
import IconCheck from '../icons/IconCheck.vue'
import IconCircle from '../icons/IconCircle.vue'
import IconCircleDot from '../icons/IconCircleDot.vue'
import IconClose from '../icons/IconClose.vue'
import RunModeNotice from './RunModeNotice.vue'

const COMMANDS = 'git pull\nuv sync\npnpm --dir frontend install'
const README_UPDATE = 'https://github.com/vateiixeira/claudio-maestro#atualizar'

const STEPS: { id: UpdateStep; label: string }[] = [
  { id: 'check', label: 'Verificando' },
  { id: 'fetch', label: 'Baixando' },
  { id: 'python', label: 'Dependências do Python' },
  { id: 'frontend-deps', label: 'Dependências do frontend' },
  { id: 'build', label: 'Compilando' },
  { id: 'restart', label: 'Reiniciando' },
]
const STATUS_ICON = { pending: IconCircle, running: IconCircleDot, done: IconCheck, failed: IconClose } as const
const STATUS_TEXT = { pending: 'pendente', running: 'em andamento', done: 'concluído', failed: 'falhou' } as const

const updates = useUpdatesStore()
const latest = computed(() => updates.state?.latest ?? null)
// Safe: markdown-it runs with `html: false`, so raw HTML in the notes is escaped.
const notesHtml = computed(() => renderMarkdown(latest.value?.notes || 'Sem notas para esta versão.'))
const published = computed(() => {
  const at = latest.value?.published_at
  return at ? new Date(at * 1000).toLocaleDateString('pt-BR', { day: 'numeric', month: 'long', year: 'numeric' }) : null
})

const selfUpdate = computed(() => updates.state?.self_update ?? null)
const job = computed(() => updates.state?.job ?? null)
const running = computed(() => job.value?.state === 'running' || job.value?.state === 'restarting')
const failed = computed(() => job.value?.state === 'failed' || job.value?.state === 'rolled-back-failed')
const upToDate = computed(() => job.value?.state === 'up-to-date')
const showSteps = computed(() => running.value || failed.value)
// Without a job (or after a failure) the manual commands stay available; only a working self-update folds them away.
const showManual = computed(() => !job.value || failed.value)
const foldManual = computed(() => !job.value && !!selfUpdate.value?.can)
const canApply = computed(() => !!selfUpdate.value?.can && (!job.value || failed.value || upToDate.value))
const commands = computed(() =>
  selfUpdate.value?.mode === 'tag'
    ? `git fetch --tags\ngit checkout --detach v${latest.value?.version}\nuv sync\npnpm --dir frontend install`
    : COMMANDS,
)
const confirmDrop = ref(false)
const liveSessions = computed(() => updates.state?.live_sessions ?? 0)
const needsConfirm = computed(() => updates.state?.agentd?.enabled === false && liveSessions.value > 0)
// Either this page already knows sessions are open, or the backend just said so (its count is newer than ours).
const confirming = computed(() => confirmDrop.value || updates.confirmSessions !== null)
const dropCount = computed(() => updates.confirmSessions ?? liveSessions.value)

function stepStatus(id: UpdateStep): 'pending' | 'running' | 'done' | 'failed' {
  // After a failure `step` is wherever the rollback got to; `failed_step` is the one that broke.
  const broken = job.value?.failed_step ?? null
  const current = broken ?? job.value?.step
  if (!job.value || !current) return 'pending'
  const at = STEPS.findIndex((s) => s.id === current)
  const index = STEPS.findIndex((s) => s.id === id)
  if (index < at) return 'done'
  if (index > at) return 'pending'
  if (broken || failed.value) return 'failed'
  if (job.value.state === 'up-to-date') return 'done'
  return 'running'
}

async function startUpdate(): Promise<void> {
  if (needsConfirm.value && !confirming.value) {
    confirmDrop.value = true
    await refocus()
    return
  }
  await updates.startUpdate(confirming.value)
  confirmDrop.value = false
  await refocus()
}

// The button that was clicked leaves the DOM (job started, or the confirmation took its place): without this the
// focus falls to <body> and the overlay's Esc and Tab handling stops receiving keys.
async function refocus(): Promise<void> {
  await nextTick()
  const next = confirmEl.value ?? dialogEl.value?.querySelector<HTMLElement>('[data-test="update-apply"]') ?? closeEl.value
  next?.focus()
}

const dialogEl = ref<HTMLElement | null>(null)
const closeEl = ref<HTMLButtonElement | null>(null)
const confirmEl = ref<HTMLButtonElement | null>(null)
const copied = ref(false)
let opener: HTMLElement | null = null
let copiedTimer: ReturnType<typeof setTimeout> | undefined

onMounted(async () => {
  opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
  // The sessions count in the store may be old (the page loaded before the sessions opened).
  updates.load().catch(() => {})
  await nextTick()
  closeEl.value?.focus()
})
onBeforeUnmount(() => {
  clearTimeout(copiedTimer)
  opener?.focus()
})

function close(): void {
  updates.closeModal()
}

// Esc and a click outside do not close the modal while the update runs; the X button always does.
function closeFromBackdrop(): void {
  if (!running.value) close()
}

async function copyCommands(): Promise<void> {
  try {
    await navigator.clipboard.writeText(commands.value)
    copied.value = true
    clearTimeout(copiedTimer)
    copiedTimer = setTimeout(() => (copied.value = false), 1500)
  } catch {
    // No clipboard permission: the commands stay visible to copy by hand.
  }
}

// Tab stays inside the dialog: from the last control it wraps to the first, and back.
function onKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Tab' || !dialogEl.value) return
  const list = Array.from(dialogEl.value.querySelectorAll<HTMLElement>('button:not([disabled]), a[href]'))
  const first = list[0]
  const last = list[list.length - 1]
  if (!first || !last) return
  const active = document.activeElement
  if (event.shiftKey && (active === first || !dialogEl.value.contains(active))) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (active === last || !dialogEl.value.contains(active))) {
    event.preventDefault()
    first.focus()
  }
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" @keydown.esc.prevent="closeFromBackdrop" @keydown="onKeydown" @click.self="closeFromBackdrop">
    <div
      v-if="latest"
      ref="dialogEl"
      data-test="update-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="update-heading"
      class="flex max-h-[85vh] w-full max-w-xl flex-col rounded-xl border border-line-strong bg-panel shadow-2xl"
    >
      <header class="flex items-start gap-3 border-b border-line px-6 py-4">
        <div class="flex min-w-0 grow flex-col gap-0.5">
          <h2 id="update-heading" class="m-0 text-base font-semibold text-fg">Versão {{ latest.version }} disponível</h2>
          <p class="m-0 text-xs text-fg-muted">
            Você está na {{ updates.state?.current }}<template v-if="published"> · publicada em {{ published }}</template>
          </p>
        </div>
        <button ref="closeEl" type="button" data-test="update-close" aria-label="Fechar" class="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-md border-none bg-transparent text-fg-muted hover:bg-card" @click="close">
          <IconClose :size="14" />
        </button>
      </header>

      <div class="flex min-h-0 flex-col gap-5 overflow-y-auto px-6 py-5">
        <div data-test="update-notes" class="markdown text-sm leading-[1.6]" v-html="notesHtml" />

        <section v-if="showSteps" class="flex flex-col gap-3" aria-labelledby="update-progress">
          <h3 id="update-progress" class="m-0 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">
            {{ job?.rolling_back ? 'Desfazendo…' : failed ? 'Atualização interrompida' : 'Atualizando' }}
          </h3>
          <ol data-test="update-steps" class="m-0 flex list-none flex-col gap-1.5 p-0 text-sm">
            <li
              v-for="s in STEPS"
              :key="s.id"
              :data-test="`update-step-${s.id}`"
              :data-status="stepStatus(s.id)"
              class="flex items-center gap-2"
              :class="stepStatus(s.id) === 'pending' ? 'text-fg-subtle' : stepStatus(s.id) === 'failed' ? 'text-secondary-soft' : 'text-fg'"
            >
              <span
                class="flex w-4 shrink-0 justify-center"
                :class="[stepStatus(s.id) === 'running' && 'motion-safe:animate-pulse', stepStatus(s.id) === 'done' && 'text-primary', stepStatus(s.id) === 'failed' && 'text-secondary']"
              ><component :is="STATUS_ICON[stepStatus(s.id)]" :size="14" /></span>
              <span>{{ s.label }}</span>
              <span class="sr-only">({{ STATUS_TEXT[stepStatus(s.id)] }})</span>
            </li>
          </ol>
          <pre v-if="job?.lines.length" data-test="update-output" class="scroll-thin m-0 max-h-40 overflow-y-auto rounded-lg border border-line bg-elevated px-3.5 py-3 font-mono text-xs whitespace-pre-wrap text-fg-muted">{{ job.lines.join('\n') }}</pre>
        </section>

        <div v-if="failed" data-test="update-failed" role="alert" class="flex flex-col gap-1.5 rounded-lg border border-secondary/50 bg-secondary-tint px-3.5 py-3 text-sm text-fg">
          <p v-if="job?.error" class="m-0 font-medium">{{ job.error }}</p>
          <p class="m-0">
            <template v-if="job?.state === 'rolled-back-failed'">Não foi possível desfazer. Rode os comandos abaixo.</template>
            <template v-else>A atualização foi desfeita; o app continua na versão {{ updates.state?.current }}.</template>
          </p>
          <p class="m-0 text-xs text-fg-muted">Log completo: {{ job?.log_path }}</p>
        </div>

        <template v-if="job?.state === 'restarting'">
          <p data-test="update-restarting" role="status" class="m-0 text-sm text-fg">Reiniciando… a página recarrega sozinha quando o app voltar.</p>
          <p v-if="updates.restartTimedOut" data-test="update-timeout" role="alert" class="m-0 rounded-lg border border-secondary/50 bg-secondary-tint px-3.5 py-3 text-sm text-fg">
            O app não voltou. Veja o log: {{ job.log_path }}
          </p>
        </template>

        <p v-if="upToDate" role="status" class="m-0 text-sm text-fg">O clone já está na versão mais nova. Reinicie o app para ver a versão {{ latest.version }}.</p>

        <template v-if="showManual">
          <p v-if="!selfUpdate?.can && !failed" data-test="update-unavailable" class="m-0 text-sm text-fg-muted">Atualização automática indisponível: {{ selfUpdate?.reason ?? 'esta instalação não informou o motivo' }}.</p>
          <RunModeNotice v-if="selfUpdate?.can && !job && updates.state?.run_mode" :run-mode="updates.state.run_mode" :port="updates.state.port" />
          <component :is="foldManual ? 'details' : 'div'" data-test="update-manual" class="flex flex-col gap-2">
            <summary v-if="foldManual" class="cursor-pointer text-xs text-fg-muted hover:text-fg">Atualizar à mão</summary>
            <h3 v-else id="update-how" class="m-0 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Para atualizar</h3>
            <div class="relative mt-2 rounded-lg border border-line bg-elevated">
              <pre data-test="update-commands" class="m-0 overflow-x-auto px-3.5 py-3 font-mono text-xs text-fg">{{ commands }}</pre>
              <button type="button" data-test="update-copy" class="absolute top-2 right-2 h-7 cursor-pointer rounded-md border border-line px-2 text-xs text-fg-muted hover:bg-card hover:text-fg" @click="copyCommands">
                {{ copied ? 'Copiado' : 'Copiar' }}
              </button>
            </div>
            <p v-if="!selfUpdate?.can" class="m-0 text-xs text-fg-muted">
              Depois, reinicie o Cláudio Maestro. Se as notas falarem do agentd, encerre-o também (as sessões em andamento caem).
              <a :href="README_UPDATE" target="_blank" rel="noopener noreferrer" class="text-fg-muted underline hover:text-fg">Como atualizar</a>
            </p>
          </component>
        </template>
      </div>

      <p v-if="updates.applyError" data-test="update-apply-error" role="alert" class="m-0 border-t border-line px-6 py-2 text-xs text-secondary-soft">{{ updates.applyError }}</p>

      <footer class="flex flex-wrap items-center justify-end gap-2 border-t border-line px-6 py-3">
        <button type="button" data-test="update-dismiss" :disabled="running" class="h-9 cursor-pointer rounded-lg border-none bg-transparent px-3.5 text-sm text-fg-muted hover:bg-card hover:text-fg disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-fg-muted" @click="updates.dismiss()">Dispensar</button>
        <template v-if="canApply">
          <template v-if="confirming">
            <span class="text-xs text-fg-muted">{{ dropCount === 1 ? '1 sessão em andamento será encerrada.' : `${dropCount} sessões em andamento serão encerradas.` }}</span>
            <button ref="confirmEl" type="button" data-test="update-confirm-drop" :disabled="updates.applying" class="h-9 cursor-pointer rounded-lg border-none bg-secondary px-3.5 text-sm font-semibold text-secondary-fg disabled:cursor-default disabled:opacity-60" @click="startUpdate">Atualizar mesmo assim</button>
          </template>
          <button v-else type="button" data-test="update-apply" :disabled="updates.applying" class="h-9 cursor-pointer rounded-lg border-none bg-primary px-3.5 text-sm font-semibold text-primary-fg hover:bg-primary-soft disabled:cursor-default disabled:opacity-60 disabled:hover:bg-primary" @click="startUpdate">{{ failed ? 'Tentar de novo' : 'Atualizar agora' }}</button>
        </template>
        <a data-test="update-github" :href="latest.url" target="_blank" rel="noopener noreferrer" class="flex h-9 items-center rounded-lg border border-line-strong px-3.5 text-sm font-medium text-fg no-underline hover:bg-card">Ver no GitHub</a>
      </footer>
    </div>
  </div>
</template>
