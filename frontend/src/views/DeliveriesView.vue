<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import DayRuler from '../components/deliveries/DayRuler.vue'
import ProjectTag from '../components/conversation/ProjectTag.vue'
import DisplayStateIcon from '../components/DisplayStateIcon.vue'
import IconAlert from '../components/icons/IconAlert.vue'
import IconCheck from '../components/icons/IconCheck.vue'
import IconChevron from '../components/icons/IconChevron.vue'
import IconCopy from '../components/icons/IconCopy.vue'
import LoadStatus from '../components/LoadStatus.vue'
import FilterChip from '../components/ui/FilterChip.vue'
import { deliveriesMarkdown, deliveryMarkdown, deliveryTitle, formatDayLong, formatTime, localDay, parseDay, projectCounts, projectMarkdown, shiftDay } from '../deliveries'
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
// While another day loads, the previous one stays on screen, dimmed, instead of vanishing.
const shown = computed(() => (store.day && (store.day.date === day.value || store.loading) ? store.day : null))
const stale = computed(() => !!shown.value && shown.value.date !== day.value)
const hasContent = computed(() => !!shown.value && (shown.value.deliveries.length > 0 || shown.value.in_progress.length > 0))
const pendingCount = computed(() => (shown.value?.deliveries ?? []).filter((d) => d.status === 'pending').length)
const colorOf = (id: number | null | undefined) => (id == null ? undefined : projects.byId(id)?.color)
const counts = computed(() => projectCounts(shown.value?.deliveries ?? []))
// The timeline: records in the order they finished.
const ordered = computed(() => [...(shown.value?.deliveries ?? [])].sort((a, b) => a.finished_at - b.finished_at || a.id - b.id))

// The project picked in the chips (null is "Todos"). Local to the screen, not in the address. If the day shown has no
// records of it (another day, for instance), it goes back to "Todos" and stays there.
const picked = ref<string | null>(null)
const project = computed(() => (picked.value !== null && counts.value.some((c) => c.project === picked.value) ? picked.value : null))
watch([shown, counts], () => {
  if (picked.value !== null && !stale.value && !counts.value.some((c) => c.project === picked.value)) picked.value = null
})
function pick(name: string | null): void {
  picked.value = name === null || name === project.value ? null : name
}
const visible = computed(() => (project.value === null ? ordered.value : ordered.value.filter((d) => d.project_name === project.value)))
const summary = computed(() => {
  const n = shown.value?.deliveries.length ?? 0
  if (!n) return 'Nenhuma entrega.'
  const p = counts.value.length
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
const copiedDelivery = ref<number | null>(null)
const copyStatus = computed(() => (copied.value === 'done' ? 'Copiado' : copiedDelivery.value !== null ? 'Entrega copiada' : ''))

const COPIED_MS = 2000
let copiedTimer: ReturnType<typeof setTimeout> | undefined
function clearCopiedTimer(): void {
  clearTimeout(copiedTimer)
  copiedTimer = undefined
}
function resetCopied(): void {
  clearCopiedTimer()
  copied.value = 'idle'
  copiedDelivery.value = null
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

async function copyText(text: string, done: () => void): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    done()
    flashCopied()
  } catch {
    clearCopiedTimer()
    copiedDelivery.value = null
    copied.value = 'failed'
  }
}

// With a project picked, "Copiar o dia" copies only that project.
async function copy(): Promise<void> {
  if (!shown.value || stale.value) return
  const text = project.value === null ? deliveriesMarkdown(shown.value) : projectMarkdown(shown.value, project.value)
  await copyText(text, () => { copiedDelivery.value = null; copied.value = 'done' })
}

async function copyDelivery(d: Delivery): Promise<void> {
  if (!shown.value || stale.value) return
  await copyText(deliveryMarkdown(d), () => { copied.value = 'idle'; copiedDelivery.value = d.id })
}

// "‹" and "›" skip the days without records when the server knows them; they never go past today.
const known = computed(() => (shown.value?.date === day.value ? shown.value : null))
const prevTarget = computed(() => known.value?.prev_day || shiftDay(day.value, -1))
const nextTarget = computed(() => {
  const next = known.value?.next_day
  return next && next > day.value && next <= localDay() ? next : shiftDay(day.value, 1)
})

// Tapping a dot on the ruler scrolls the timeline to the record and flashes it.
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
  store.release()
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
          <IconCopy :size="14" />{{ copied === 'done' ? 'Copiado' : 'Copiar o dia' }}
        </button>
        <span data-test="copy-status" class="sr-only" aria-live="polite">{{ copyStatus }}</span>
      </div>
    </header>
    <p v-if="copied === 'failed'" role="alert" class="m-0 text-sm text-diff-del-fg">Não foi possível copiar.</p>
    <div v-if="store.error" role="alert" class="flex flex-wrap items-center gap-2">
      <p class="m-0 text-sm text-diff-del-fg">{{ store.error }}</p>
      <button type="button" data-test="retry-day" class="h-8 rounded-md border border-line-strong px-2.5 text-xs text-fg hover:bg-card" @click="store.load(day)">Tentar de novo</button>
    </div>

    <div v-if="shown && shown.deliveries.length" role="group" aria-label="Filtrar por projeto" class="flex flex-wrap items-center gap-2">
      <FilterChip data-test="delivery-filter" data-project="" label="Todos" :count="shown.deliveries.length" :pressed="project === null" @toggle="pick(null)" />
      <FilterChip v-for="c in counts" :key="c.project" data-test="delivery-filter" :data-project="c.project" :label="c.project" :count="c.count" :pressed="project === c.project" @toggle="pick(c.project)">
        <template #icon>
          <span class="size-2 shrink-0 rounded-[2px]" :class="colorOf(c.projectId) ? '' : 'bg-fg-subtle'" :style="colorOf(c.projectId) ? { backgroundColor: colorOf(c.projectId) } : undefined" />
        </template>
      </FilterChip>
    </div>

    <div v-if="shown" data-test="day-content" :aria-busy="stale" :class="['flex min-h-0 flex-1 flex-col gap-6 md:flex-row md:gap-10', stale ? 'opacity-60' : '']">
      <div class="flex min-h-0 min-w-0 flex-1 flex-col gap-2">
        <p v-if="!shown.deliveries.length" class="m-0 text-sm text-fg-muted">Nada finalizado neste dia.</p>
        <DayRuler v-if="visible.length" :deliveries="visible" @select="showDelivery" />

        <ol v-if="visible.length" data-test="delivery-timeline" class="scroll-thin relative m-0 flex list-none flex-col p-0 pb-4 before:absolute before:top-2 before:bottom-4 before:left-[4.15625rem] before:w-px before:bg-line md:min-h-0 md:flex-1 md:overflow-y-auto">
          <li
            v-for="d in visible" :key="d.id" data-test="delivery" :data-delivery-id="d.id"
            :data-highlighted="highlighted === d.id ? 'true' : undefined"
            class="group relative grid grid-cols-[2.875rem_0.875rem_minmax(0,1fr)_1.75rem] gap-x-3.5 pb-[1.125rem]"
          >
            <span data-test="delivery-time" class="mt-0.5 text-right font-mono text-xs text-fg-subtle tabular-nums">{{ formatTime(d.finished_at) }}</span>
            <span
              data-test="delivery-dot"
              class="mt-[0.3125rem] ml-0.5 size-[0.5625rem] rounded-full ring-4 ring-surface"
              :class="colorOf(d.project_id) ? '' : 'bg-fg-subtle'"
              :style="colorOf(d.project_id) ? { backgroundColor: colorOf(d.project_id) } : undefined"
            />
            <div class="-mx-2 -my-1 min-w-0 rounded-lg px-2 py-1 group-data-[highlighted=true]:bg-card group-data-[highlighted=true]:ring-1 group-data-[highlighted=true]:ring-line-strong">
              <ProjectTag v-if="d.project_id != null && projects.byId(d.project_id)" :project-id="d.project_id" />
              <span v-else data-test="project-tag" class="flex min-w-0 items-center gap-1.5 text-xs text-fg-muted">
                <span class="size-2 shrink-0 rounded-[2px] bg-fg-subtle" />
                <span class="truncate">{{ d.project_name }}</span>
              </span>
              <h2 class="m-0 mt-1 break-words text-[0.9375rem] leading-[1.4] font-semibold text-fg">
                <RouterLink v-if="d.session_id" :to="`/sessions/${d.session_id}`" class="text-inherit no-underline hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary">{{ deliveryTitle(d) }}</RouterLink>
                <template v-else>{{ deliveryTitle(d) }}</template>
              </h2>
              <ul v-if="d.bullets.length" :class="['m-0 mt-1 break-words text-[0.84375rem] leading-normal text-fg-muted', detailed || expanded[d.id] ? 'list-disc space-y-1 pl-4 marker:text-fg-subtle' : 'list-none p-0']">
                <li v-for="(b, j) in visibleBullets(d)" :key="j" :class="detailed || expanded[d.id] ? '' : 'line-clamp-2'">{{ b }}</li>
              </ul>
              <button
                v-if="!detailed && d.bullets.length > 1" data-test="more-bullets" type="button" :aria-expanded="!!expanded[d.id]"
                class="mt-1.5 inline-flex items-center gap-1 text-[0.78125rem] text-fg-subtle hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                @click="toggleBullets(d.id)"
              >{{ expanded[d.id] ? 'Mostrar menos' : `Mais ${d.bullets.length - 1} ${d.bullets.length - 1 === 1 ? 'item' : 'itens'}` }}<IconChevron :size="12" :open="!!expanded[d.id]" /></button>
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
                  class="text-sm text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-40 disabled:no-underline"
                  :disabled="store.busy[d.id]"
                  @click="store.summarize(d.id)"
                >{{ d.status === 'error' ? 'Tentar de novo' : 'Resumir' }}</button>
              </div>
            </div>
            <button
              data-test="copy-delivery" type="button"
              aria-label="Copiar esta entrega" title="Copiar esta entrega"
              :data-copied="copiedDelivery === d.id ? 'true' : undefined"
              class="flex size-7 items-center justify-center rounded-lg text-fg-subtle hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
              @click="copyDelivery(d)"
            ><IconCheck v-if="copiedDelivery === d.id" :size="14" class="text-primary" /><IconCopy v-else :size="14" /></button>
          </li>
        </ol>
      </div>

      <section v-if="shown.in_progress.length" data-test="in-progress" aria-labelledby="in-progress-title" class="flex min-h-0 min-w-0 flex-col md:w-[15.625rem] md:shrink-0 md:pt-3.5">
        <div class="flex items-center gap-2">
          <DisplayStateIcon display="running" :size="13" />
          <h2 id="in-progress-title" class="m-0 grow text-sm font-semibold text-fg">Em andamento</h2>
          <span data-test="lane-count" class="font-mono text-xs text-fg-subtle tabular-nums">{{ shown.in_progress.length }}</span>
        </div>
        <div class="scroll-thin flex min-h-0 flex-1 flex-col pt-1.5 md:overflow-y-auto">
          <RouterLink
            v-for="s in shown.in_progress" :key="s.session_id" :to="`/sessions/${s.session_id}`" :title="s.short ?? undefined"
            class="flex min-h-8 min-w-0 items-center gap-2 rounded-md text-[0.8125rem] text-fg-muted no-underline hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          >
            <span class="size-2 shrink-0 rounded-[2px]" :class="colorOf(s.project_id) ? '' : 'bg-fg-subtle'" :style="colorOf(s.project_id) ? { backgroundColor: colorOf(s.project_id) } : undefined" />
            <span class="min-w-0 truncate">{{ s.title }}</span>
          </RouterLink>
        </div>
      </section>
    </div>
    <LoadStatus v-else-if="store.loading" state="loading" />
  </div>
</template>
