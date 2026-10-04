<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { errorMessage, getDigestConfig, listDigestRuns, putDigestConfig, runDigest } from '../../api/http'
import { MAX_INSTRUCTIONS, digestConfigProblem, digestStatusText, type DigestForm } from '../../digestConfig'
import { formatActivity } from '../../format'
import { ALL_EFFORTS, EFFORT_LABELS } from '../../sessionOptions'
import { useDigestStore } from '../../stores/digest'
import { useModelsStore } from '../../stores/models'
import type { DigestConfig, DigestRun } from '../../types/api'

const digest = useDigestStore()
const models = useModelsStore()

const TRIGGER_LABELS: Record<DigestRun['trigger'], string> = {
  auto: 'Automática',
  manual_all: 'Rodar agora',
  manual_session: 'Resumir conversa',
}

const form = reactive<DigestForm>({
  enabled: false, model: 'sonnet', effort: 'medium', extra_instructions: '',
  interval_minutes: '10', min_new_messages: '10', open_turn_minutes: '30', window_days: '3', closure_auto: true,
})
const loading = ref(true)
const loadError = ref<string | null>(null)
const saving = ref(false)
const saved = ref(false)
const error = ref<string | null>(null)
const runs = ref<DigestRun[]>([])
const runsError = ref<string | null>(null)
const open = ref<Record<number, boolean>>({})
const starting = ref(false)

const ready = computed(() => !loading.value && loadError.value === null)
const running = computed(() => digest.status?.running ?? false)
const statusText = computed(() => digestStatusText(digest.status))
// The saved model stays selectable even when the SDK list no longer has it.
const modelOptions = computed(() => {
  const list = models.models.map((m) => ({ value: m.value, label: m.displayName || m.value }))
  if (form.model && !list.some((m) => m.value === form.model)) list.unshift({ value: form.model, label: form.model })
  return list
})

function fill(config: DigestConfig) {
  form.enabled = config.enabled
  form.model = config.model
  form.effort = config.effort
  form.extra_instructions = config.extra_instructions
  form.interval_minutes = String(config.interval_minutes)
  form.min_new_messages = String(config.min_new_messages)
  form.open_turn_minutes = String(config.open_turn_minutes)
  form.window_days = String(config.window_days)
  form.closure_auto = config.closure_auto ?? true
}

async function loadRuns() {
  try {
    runs.value = await listDigestRuns()
    runsError.value = null
  } catch (e) {
    runsError.value = errorMessage(e)
  }
}

async function load() {
  loading.value = true
  loadError.value = null
  try {
    const state = await getDigestConfig()
    fill(state.config)
    digest.applyStatus(state.status)
    saved.value = false
  } catch (e) {
    loadError.value = errorMessage(e)
  } finally {
    loading.value = false
  }
  void models.ensure()
  void loadRuns()
}

watch(form, () => { saved.value = false })
// A pass finished: its line in the log changed.
watch(running, (now, before) => { if (before && !now) void loadRuns() })

async function save() {
  if (!ready.value || saving.value) return
  error.value = null
  saved.value = false
  const problem = digestConfigProblem(form)
  if (problem) {
    error.value = problem
    return
  }
  saving.value = true
  try {
    const state = await putDigestConfig({
      enabled: form.enabled,
      model: form.model,
      effort: form.effort,
      extra_instructions: form.extra_instructions,
      interval_minutes: Number(form.interval_minutes),
      min_new_messages: Number(form.min_new_messages),
      open_turn_minutes: Number(form.open_turn_minutes),
      window_days: Number(form.window_days),
      closure_auto: form.closure_auto,
    })
    fill(state.config)
    digest.applyStatus(state.status)
    await nextTick() // let the form watcher run before confirming
    saved.value = true
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    saving.value = false
  }
}

async function runNow() {
  if (running.value || starting.value) return
  starting.value = true
  error.value = null
  try {
    digest.applyStatus(await runDigest())
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    starting.value = false
  }
}

onMounted(load)

const label = 'font-mono text-xs tracking-[0.08em] text-fg-subtle uppercase'
const input = 'h-11 rounded-lg border border-line-strong bg-elevated px-3.5 text-sm text-fg outline-none focus:border-fg-muted disabled:opacity-40'
</script>

<template>
  <div class="flex flex-col">
    <div v-if="loadError" class="flex flex-col items-start gap-3 px-7 py-6">
      <p role="alert" class="m-0 w-full rounded-lg border border-diff-del-fg/40 bg-diff-del-bg px-3.5 py-2.5 text-sm text-diff-del-fg">
        Não foi possível ler a configuração do agente. {{ loadError }}
      </p>
      <button type="button" class="h-11 rounded-lg border border-line-strong px-4 font-medium text-fg hover:bg-card" @click="load">Tentar de novo</button>
    </div>

    <form class="flex flex-col" aria-label="Agente de resumos" :aria-busy="loading" @submit.prevent="save">
      <div class="flex flex-col gap-6 px-7 py-6">
        <p class="m-0 text-sm text-fg-muted">
          Lê as conversas em andamento de tempos em tempos e mantém um resumo em fases de cada uma, visível em Detalhes e na lista de conversas. Só lê: não executa comandos nem altera arquivos. Cada leitura usa a sua assinatura.
        </p>

        <div class="flex items-center justify-between gap-4">
          <label for="digest-enabled" class="flex items-center gap-3 text-sm font-medium text-fg">
            <input id="digest-enabled" v-model="form.enabled" type="checkbox" role="switch" :disabled="!ready" class="size-5 accent-[var(--color-primary)]" />
            Ligado
          </label>
          <span data-test="digest-status" role="status" class="text-sm text-fg-muted">{{ statusText }}</span>
        </div>

        <div class="flex flex-col gap-1.5">
          <label for="digest-closure-auto" class="flex items-center gap-3 text-sm font-medium text-fg">
            <input id="digest-closure-auto" v-model="form.closure_auto" type="checkbox" role="switch" :disabled="!ready" class="size-5 accent-[var(--color-primary)]" />
            Verificar entrega automaticamente
          </label>
          <p class="m-0 text-xs text-fg-muted">Confere se a conversa pode ser fechada alguns minutos depois de o turno terminar. Desligada, a verificação só roda pelo Resumir agora.</p>
        </div>

        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div class="flex flex-col gap-2">
            <label for="digest-model" :class="label">Modelo</label>
            <select id="digest-model" v-model="form.model" :disabled="!ready" :class="input">
              <option v-for="m in modelOptions" :key="m.value" :value="m.value">{{ m.label }}</option>
            </select>
          </div>
          <div class="flex flex-col gap-2">
            <label for="digest-effort" :class="label">Raciocínio</label>
            <select id="digest-effort" v-model="form.effort" :disabled="!ready" :class="input">
              <option v-for="e in ALL_EFFORTS" :key="e" :value="e">{{ EFFORT_LABELS[e] }}</option>
            </select>
          </div>
        </div>

        <div class="flex flex-col gap-2">
          <label for="digest-instructions" :class="label">Instruções extras</label>
          <textarea
            id="digest-instructions"
            v-model="form.extra_instructions"
            rows="4"
            :maxlength="MAX_INSTRUCTIONS"
            :disabled="!ready"
            aria-describedby="digest-instructions-help"
            class="rounded-lg border border-line-strong bg-elevated px-3.5 py-2.5 text-sm text-fg outline-none focus:border-fg-muted disabled:opacity-40"
          />
          <p id="digest-instructions-help" class="m-0 flex justify-between text-xs text-fg-muted">
            <span>Somadas às regras fixas do agente. Ex.: "cite sempre o número da tarefa".</span>
            <span>{{ form.extra_instructions.length }}/{{ MAX_INSTRUCTIONS }}</span>
          </p>
        </div>

        <div class="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div class="flex flex-col gap-2">
            <label for="digest-interval" :class="label">Intervalo (min)</label>
            <input id="digest-interval" v-model="form.interval_minutes" type="number" inputmode="numeric" min="2" max="240" step="1" :disabled="!ready" :class="input" />
          </div>
          <div class="flex flex-col gap-2">
            <label for="digest-min" :class="label">Mínimo de mensagens</label>
            <input id="digest-min" v-model="form.min_new_messages" type="number" inputmode="numeric" min="1" max="500" step="1" :disabled="!ready" :class="input" />
          </div>
          <div class="flex flex-col gap-2">
            <label for="digest-open-turn" :class="label">Teto com turno aberto (min)</label>
            <input id="digest-open-turn" v-model="form.open_turn_minutes" type="number" inputmode="numeric" min="5" max="480" step="1" :disabled="!ready" :class="input" />
          </div>
          <div class="flex flex-col gap-2">
            <label for="digest-window" :class="label">Janela (dias)</label>
            <input id="digest-window" v-model="form.window_days" type="number" inputmode="numeric" min="1" max="30" step="1" :disabled="!ready" :class="input" />
          </div>
        </div>
        <p class="m-0 text-xs text-fg-muted">
          Uma conversa é lida de novo quando tem pelo menos o mínimo de mensagens novas e o turno terminou, ou quando o turno está aberto há mais que o teto. Conversas finalizadas ou paradas há mais dias que a janela não são lidas.
        </p>
      </div>

      <p v-if="error" role="alert" class="mx-7 mb-4 rounded-lg border border-diff-del-fg/40 bg-diff-del-bg px-3.5 py-2.5 text-sm text-diff-del-fg">{{ error }}</p>

      <footer class="flex items-center justify-end gap-3 border-t border-line px-7 pt-4 pb-5">
        <p v-if="saved" data-test="digest-saved" role="status" class="m-0 text-sm text-primary-soft">Configuração salva</p>
        <button
          type="button"
          data-test="digest-run"
          class="h-11 rounded-lg border border-line-strong px-4 font-medium text-fg hover:bg-card disabled:cursor-not-allowed disabled:opacity-40"
          :disabled="!ready || running || starting"
          @click="runNow"
        >Rodar agora</button>
        <button
          type="submit"
          data-test="digest-save"
          class="h-11 rounded-lg bg-primary px-[18px] font-semibold text-primary-fg hover:bg-primary-soft disabled:cursor-not-allowed disabled:opacity-40"
          :disabled="!ready || saving"
        >{{ saving ? 'Salvando…' : 'Salvar' }}</button>
      </footer>
    </form>

    <section aria-labelledby="digest-runs-title" class="flex flex-col gap-2 border-t border-line px-7 py-6">
      <h2 id="digest-runs-title" class="m-0 font-mono text-xs tracking-[0.08em] text-fg-subtle uppercase">Últimas passadas</h2>
      <p v-if="runsError" role="alert" class="m-0 text-sm text-diff-del-fg">{{ runsError }}</p>
      <p v-else-if="runs.length === 0" class="m-0 text-sm text-fg-muted">Nenhuma passada ainda.</p>
      <table v-else data-test="digest-runs" class="w-full text-left text-sm">
        <thead class="text-xs text-fg-subtle">
          <tr><th class="py-1 font-normal">Quando</th><th class="font-normal">Origem</th><th class="font-normal">Lidas</th><th class="font-normal">Puladas</th><th class="font-normal">Erros</th></tr>
        </thead>
        <tbody>
          <template v-for="run in runs" :key="run.id">
            <tr data-test="digest-run-row" class="border-t border-line">
              <td class="py-1.5">{{ formatActivity(run.started_at) }}</td>
              <td>{{ TRIGGER_LABELS[run.trigger] }}</td>
              <td>{{ run.read_count }}</td>
              <td>{{ run.skipped_count }}</td>
              <td>
                <button
                  v-if="run.errors.length || run.stopped"
                  type="button"
                  data-test="digest-run-toggle"
                  :aria-expanded="!!open[run.id]"
                  class="rounded px-1 text-diff-del-fg hover:bg-card"
                  @click="open = { ...open, [run.id]: !open[run.id] }"
                >{{ run.errors.length }}{{ run.stopped ? ' · parou' : '' }}</button>
                <span v-else class="text-fg-muted">0</span>
              </td>
            </tr>
            <tr v-if="open[run.id]" data-test="digest-run-details">
              <td colspan="5" class="pb-2 text-xs text-fg-muted">
                <p v-if="run.stopped" class="m-0">Parou: {{ run.stopped }}</p>
                <p v-for="e in run.errors" :key="e.session_id" class="m-0">{{ e.title }}: {{ e.message }}</p>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </section>
  </div>
</template>
