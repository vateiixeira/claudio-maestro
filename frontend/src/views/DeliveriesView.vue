<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import DayRuler from '../components/deliveries/DayRuler.vue'
import DisplayStateIcon from '../components/DisplayStateIcon.vue'
import IconAlert from '../components/icons/IconAlert.vue'
import IconCheck from '../components/icons/IconCheck.vue'
import IconChevron from '../components/icons/IconChevron.vue'
import IconCopy from '../components/icons/IconCopy.vue'
import LoadStatus from '../components/LoadStatus.vue'
import { deliveriesMarkdown, deliveryTitle, formatDayLong, formatTime, groupByProject, localDay, parseDay, projectMarkdown, shiftDay } from '../deliveries'
import { readDeliveriesDetail, writeDeliveriesDetail } from '../deliveriesDetailPref'
import { deliveriesShortcut } from '../deliveriesShortcut'
import { useDeliveriesStore } from '../stores/deliveries'
import { useProjectsStore } from '../stores/projects'
import type { Delivery } from '../types/api'

const route = useRoute()
const router = useRouter()
const store = useDeliveriesStore()
const projects = useProjectsStore()

// Only a real date, today or earlier; anything else in `?dia=` falls back to today.
const isDay = (v: unknown): v is string => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) && localDay(parseDay(v)) === v && v <= localDay()
const day = computed(() => (isDay(route.query.dia) ? route.query.dia : localDay()))
const isToday = computed(() => day.value >= localDay())
// Lanes in alphabetical order, so a project keeps its place from one day to the next.
const groups = computed(() => groupByProject(store.day?.deliveries ?? []).sort((a, b) => a.project.localeCompare(b.project, 'pt-BR')))
// While another day loads, the previous one stays on screen, dimmed, instead of vanishing.
const shown = computed(() => (store.day && (store.day.date === day.value || store.loading) ? store.day : null))
const stale = computed(() => !!shown.value && shown.value.date !== day.value)
const hasContent = computed(() => !!shown.value && (shown.value.deliveries.length > 0 || shown.value.in_progress.length > 0))
const pendingCount = computed(() => (shown.value?.deliveries ?? []).filter((d) => d.status === 'pending').length)
const colorOf = (id: number | null | undefined) => (id == null ? undefined : projects.byId(id)?.color)
const projectColor = (list: Delivery[]) => colorOf(list[0]?.project_id)
const summary = computed(() => {
  const n = shown.value?.deliveries.length ?? 0
  if (!n) return 'Nenhuma entrega.'
  const p = groups.value.length
  const text = `${n} ${n === 1 ? 'entrega' : 'entregas'} em ${p} ${p === 1 ? 'projeto' : 'projetos'}.`
  const open = pendingCount.value
  if (!open) return text
  return `${text} ${open} ${open === 1 ? 'resumo ainda sendo escrito' : 'resumos ainda sendo escritos'}.`
})

// Summary mode shows the first bullet of each record; detailed mode (kept between visits) shows them all.
const detailed = ref(readDeliveriesDetail())
function toggleDetail(): void {
  detailed.value = !detailed.value
  writeDeliveriesDetail(detailed.value)
}
const expanded = ref<Record<number, boolean>>({})
const visibleBullets = (d: Delivery) => (detailed.value || expanded.value[d.id] ? d.bullets : d.bullets.slice(0, 1))
function toggleBullets(id: number): void {
  expanded.value = { ...expanded.value, [id]: !expanded.value[id] }
}

const copied = ref<'idle' | 'done' | 'failed'>('idle')
const copiedProject = ref<string | null>(null)
const copyStatus = computed(() => (copied.value === 'done' ? 'Copiado' : copiedProject.value ? `${copiedProject.value} copiado` : ''))

const COPIED_MS = 2000
let copiedTimer: ReturnType<typeof setTimeout> | undefined
function clearCopiedTimer(): void {
  clearTimeout(copiedTimer)
  copiedTimer = undefined
}
function resetCopied(): void {
  clearCopiedTimer()
  copied.value = 'idle'
  copiedProject.value = null
}
function flashCopied(): void {
  clearCopiedTimer()
  copiedTimer = setTimeout(resetCopied, COPIED_MS)
}

// The record flashed after a tap on the ruler.
const highlighted = ref<number | null>(null)
let highlightTimer: ReturnType<typeof setTimeout> | undefined

watch(day, (d) => { resetCopied(); clearTimeout(highlightTimer); highlighted.value = null; void store.load(d) }, { immediate: true })

function go(d: string): void {
  void router.push({ name: 'deliveries', query: d === localDay() ? {} : { dia: d } })
}

async function copy(): Promise<void> {
  if (!shown.value || stale.value) return
  try {
    await navigator.clipboard.writeText(deliveriesMarkdown(shown.value))
    copiedProject.value = null
    copied.value = 'done'
    flashCopied()
  } catch {
    clearCopiedTimer()
    copied.value = 'failed'
  }
}

async function copyProject(project: string): Promise<void> {
  if (!shown.value || stale.value) return
  try {
    await navigator.clipboard.writeText(projectMarkdown(shown.value, project))
    copied.value = 'idle'
    copiedProject.value = project
    flashCopied()
  } catch {
    clearCopiedTimer()
    copiedProject.value = null
    copied.value = 'failed'
  }
}

// "‹" and "›" skip the days without records when the server knows them; they never go past today.
const known = computed(() => (shown.value?.date === day.value ? shown.value : null))
const prevTarget = computed(() => known.value?.prev_day || shiftDay(day.value, -1))
const nextTarget = computed(() => {
  const next = known.value?.next_day
  return next && next > day.value && next <= localDay() ? next : shiftDay(day.value, 1)
})

// Tapping a dot on the ruler scrolls the lane to the record and flashes it.
const root = ref<HTMLElement | null>(null)
const HIGHLIGHT_MS = 1500
function showDelivery(id: number): void {
  const el = root.value?.querySelector<HTMLElement>(`[data-delivery-id="${id}"]`)
  if (!el) return
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches
  el.scrollIntoView?.({ block: 'nearest', inline: 'nearest', behavior: reduce ? 'auto' : 'smooth' })
  clearTimeout(highlightTimer)
  highlighted.value = id
  highlightTimer = setTimeout(() => { highlighted.value = null }, HIGHLIGHT_MS)
}

function onKey(event: KeyboardEvent): void {
  const action = deliveriesShortcut(event)
  if (action === 'prev') {
    event.preventDefault()
    go(prevTarget.value)
  } else if (action === 'next') {
    if (isToday.value) return
    event.preventDefault()
    go(nextTarget.value)
  } else if (action === 'copy' && hasContent.value && !stale.value) {
    event.preventDefault()
    void copy()
  }
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKey)
  clearCopiedTimer()
  clearTimeout(highlightTimer)
})
</script>

<template>
  <div ref="root" class="flex min-h-full flex-col gap-4 px-6 py-6 md:h-full md:min-h-0">
    <header class="flex flex-wrap items-start gap-x-4 gap-y-3">
      <div class="min-w-0 grow">
        <h1 class="m-0 text-lg font-semibold text-fg">{{ formatDayLong(day) }}</h1>
        <p v-if="shown" data-test="day-summary" class="m-0 text-sm text-fg-muted">{{ summary }}</p>
      </div>
      <div class="flex flex-wrap items-center gap-4">
        <button data-test="toggle-detail" type="button" :aria-pressed="detailed" class="h-9 rounded-md border border-line-strong px-3 text-sm text-fg hover:bg-card" @click="toggleDetail">{{ detailed ? 'Detalhado' : 'Resumido' }}</button>
        <div data-test="day-nav" class="flex h-9 items-stretch divide-x divide-line-strong overflow-hidden rounded-md border border-line-strong">
          <button data-test="prev-day" type="button" aria-label="Dia anterior" class="flex w-9 items-center justify-center text-fg hover:bg-card" @click="go(prevTarget)"><IconChevron :size="14" class="rotate-180" /></button>
          <button data-test="today" type="button" class="px-3 text-sm text-fg hover:bg-card disabled:cursor-default disabled:text-fg-subtle disabled:hover:bg-transparent" :disabled="isToday" @click="go(localDay())">Hoje</button>
          <button data-test="next-day" type="button" aria-label="Próximo dia" class="flex w-9 items-center justify-center text-fg hover:bg-card disabled:cursor-default disabled:text-fg-subtle disabled:hover:bg-transparent" :disabled="isToday" @click="go(nextTarget)"><IconChevron :size="14" /></button>
        </div>
        <button data-test="copy" type="button" class="flex h-9 items-center gap-1.5 rounded-md bg-primary px-3 text-sm font-semibold text-primary-fg hover:bg-primary-soft disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-primary" :disabled="!hasContent || stale" @click="copy">
          <IconCopy :size="14" />{{ copied === 'done' ? 'Copiado' : 'Copiar' }}
        </button>
        <span data-test="copy-status" class="sr-only" aria-live="polite">{{ copyStatus }}</span>
      </div>
    </header>
    <p v-if="copied === 'failed'" role="alert" class="m-0 text-sm text-diff-del-fg">Não foi possível copiar.</p>
    <div v-if="store.error" role="alert" class="flex flex-wrap items-center gap-2">
      <p class="m-0 text-sm text-diff-del-fg">{{ store.error }}</p>
      <button type="button" data-test="retry-day" class="h-8 rounded-md border border-line-strong px-2.5 text-xs text-fg hover:bg-card" @click="store.load(day)">Tentar de novo</button>
    </div>

    <div v-if="shown" data-test="day-content" :aria-busy="stale" :class="['flex min-h-0 flex-1 flex-col gap-4 md:flex-row', stale ? 'opacity-60' : '']">
      <div class="flex min-h-0 min-w-0 flex-1 flex-col gap-4">
        <p v-if="!shown.deliveries.length" class="m-0 text-sm text-fg-muted">Nada finalizado neste dia.</p>
        <DayRuler v-if="shown.deliveries.length" :deliveries="shown.deliveries" @select="showDelivery" />

        <div
          v-if="groups.length"
          data-test="delivery-grid"
          class="scroll-thin grid grid-flow-row gap-4 pb-2 md:min-h-0 md:flex-1 md:auto-cols-[minmax(20rem,1fr)] md:grid-flow-col md:grid-rows-[minmax(0,1fr)] md:overflow-x-auto"
        >
          <section v-for="group in groups" :key="group.project" data-test="delivery-group" class="flex min-h-0 min-w-0 flex-col rounded-xl bg-panel">
            <div class="flex items-center gap-2 px-4 pt-3 pb-2">
              <h2 class="m-0 flex min-w-0 grow items-center gap-2 text-sm font-semibold text-fg">
                <span data-test="project-swatch" class="size-2.5 shrink-0 rounded-[3px]" :class="projectColor(group.items) ? '' : 'bg-fg-subtle'" :style="projectColor(group.items) ? { backgroundColor: projectColor(group.items) } : undefined" />
                <span class="min-w-0 truncate">{{ group.project }}</span>
              </h2>
              <span data-test="lane-count" class="text-xs text-fg-subtle tabular-nums">{{ group.items.length }}</span>
              <button
                data-test="copy-project" type="button"
                :aria-label="`Copiar ${group.project}`" :title="`Copiar ${group.project}`"
                :data-copied="copiedProject === group.project ? 'true' : undefined"
                class="flex size-7 shrink-0 items-center justify-center rounded-md text-fg-subtle hover:bg-card hover:text-fg"
                @click="copyProject(group.project)"
              ><IconCheck v-if="copiedProject === group.project" :size="14" class="text-primary" /><IconCopy v-else :size="14" /></button>
            </div>
            <div class="scroll-thin flex min-h-0 flex-1 flex-col gap-1 px-2 pb-2 md:overflow-y-auto">
              <article
                v-for="d in group.items" :key="d.id" data-test="delivery" :data-delivery-id="d.id"
                :class="['flex min-w-0 gap-3 rounded-lg px-3 py-2.5 hover:bg-card', highlighted === d.id ? 'bg-card ring-1 ring-line-strong' : '']"
              >
                <span data-test="delivery-time" class="w-11 shrink-0 pt-0.5 text-xs text-fg-subtle tabular-nums">{{ formatTime(d.finished_at) }}</span>
                <div class="min-w-0 flex-1">
                  <RouterLink v-if="d.session_id" :to="`/sessions/${d.session_id}`" class="block break-words text-sm font-medium text-fg no-underline hover:underline">{{ deliveryTitle(d) }}</RouterLink>
                  <span v-else class="block break-words text-sm font-medium text-fg">{{ deliveryTitle(d) }}</span>
                  <ul v-if="d.bullets.length" class="m-0 mt-1.5 list-disc space-y-1 break-words pl-4 text-[13px] leading-5 text-fg-muted marker:text-fg-subtle">
                    <li v-for="(b, j) in visibleBullets(d)" :key="j">{{ b }}</li>
                  </ul>
                  <button v-if="!detailed && d.bullets.length > 1" data-test="more-bullets" type="button" class="mt-1 flex items-center gap-1 text-xs text-fg-subtle hover:text-fg" @click="toggleBullets(d.id)">
                    <IconChevron :size="10" :open="!!expanded[d.id]" />{{ expanded[d.id] ? 'menos' : `+ ${d.bullets.length - 1} ${d.bullets.length - 1 === 1 ? 'item' : 'itens'}` }}
                  </button>
                  <p v-if="d.status === 'pending'" class="m-0 mt-2 flex items-center gap-1.5 text-sm text-fg-muted"><DisplayStateIcon display="running" :size="12" />Resumindo…</p>
                  <p v-if="store.actionErrors[d.id]" role="alert" class="m-0 mt-2 text-sm text-diff-del-fg">{{ store.actionErrors[d.id] }}</p>
                  <div v-if="d.status === 'error' || d.status === 'title_only'" class="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                    <span v-if="d.status === 'error'" class="flex min-w-0 items-start gap-1.5 text-diff-del-fg">
                      <span data-test="error-icon" class="mt-0.5 flex"><IconAlert :size="14" /></span>
                      <span class="min-w-0 break-words">{{ d.error }}</span>
                    </span>
                    <span v-else class="text-xs text-fg-subtle">só título</span>
                    <button
                      v-if="shown.agent_enabled"
                      data-test="summarize" type="button"
                      class="text-sm text-primary hover:underline disabled:cursor-not-allowed disabled:opacity-40 disabled:no-underline"
                      :disabled="store.busy[d.id]"
                      @click="store.summarize(d.id)"
                    >{{ d.status === 'error' ? 'Tentar de novo' : 'Resumir' }}</button>
                  </div>
                </div>
              </article>
            </div>
          </section>
        </div>
      </div>

      <section v-if="shown.in_progress.length" data-test="in-progress" aria-labelledby="in-progress-title" class="flex min-h-0 min-w-0 flex-col rounded-xl border border-dashed border-line bg-bg md:mb-2 md:w-72 md:shrink-0">
        <div class="flex items-center gap-2 px-4 pt-3 pb-2">
          <DisplayStateIcon display="running" :size="12" />
          <h2 id="in-progress-title" class="m-0 grow text-sm font-semibold text-fg">Em andamento</h2>
          <span data-test="lane-count" class="text-xs text-fg-subtle tabular-nums">{{ shown.in_progress.length }}</span>
        </div>
        <div class="scroll-thin flex min-h-0 flex-1 flex-col gap-1 px-2 pb-2 md:overflow-y-auto">
          <RouterLink v-for="s in shown.in_progress" :key="s.session_id" :to="`/sessions/${s.session_id}`" :title="s.short ?? undefined" class="flex min-w-0 flex-col gap-0.5 rounded-lg px-3 py-2 no-underline hover:bg-card">
            <span class="break-words text-sm text-fg">{{ s.title }}</span>
            <span class="flex items-center gap-1.5 text-xs text-fg-subtle">
              <span class="size-2 shrink-0 rounded-[2px]" :class="colorOf(s.project_id) ? '' : 'bg-fg-subtle'" :style="colorOf(s.project_id) ? { backgroundColor: colorOf(s.project_id) } : undefined" />
              <span class="min-w-0 truncate">{{ s.project_name }}</span>
            </span>
          </RouterLink>
        </div>
      </section>
    </div>
    <LoadStatus v-else-if="store.loading" state="loading" />
  </div>
</template>
