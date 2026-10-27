<script setup lang="ts">
import { onBeforeUnmount, reactive, ref } from 'vue'
import { errorMessage, request } from '../../api/http'
const props = defineProps<{ projectId: number }>()
const key = `maestro:collection:${props.projectId}`
let saved: Record<string, string> = {}
try { saved = JSON.parse(localStorage.getItem(key) ?? '{}') } catch {}
const form = reactive({ source: saved.source ?? 'sentry', source_instance: saved.source_instance ?? '', source_project: saved.source_project ?? '', query: saved.query ?? '' })
const busy = ref(false), error = ref(''), receipt = ref(''), collections = ref<Record<string, unknown>[]>([]), selected = ref<Record<string, unknown> | null>(null)
let alive = true
async function load() { try { const result = await request<{ items: Record<string, unknown>[] }>('GET', `/api/projects/${props.projectId}/collections`); if (alive) collections.value = result.items ?? [] } catch (e) { if (alive) error.value = errorMessage(e) } }
async function collect() {
  if (busy.value || !form.source_instance.trim() || !form.source_project.trim()) return
  busy.value = true; error.value = ''; receipt.value = ''
  try { localStorage.setItem(key, JSON.stringify(form)); const result = await request<Record<string, unknown>>('POST', `/api/projects/${props.projectId}/collections`, form); receipt.value = `Coleta registrada${result.id ? ` #${result.id}` : ''}. O CTO receberá os metadados, sem iniciar trabalhadores duplicados.`; await load() }
  catch (e) { error.value = errorMessage(e) }
  finally { busy.value = false }
}
async function inspect(id: unknown) { try { selected.value = await request('GET', `/api/projects/${props.projectId}/collections/${encodeURIComponent(String(id))}`) } catch (e) { error.value = errorMessage(e) } }
void load()
onBeforeUnmount(() => { alive = false })
</script>
<template><section class="sources-panel" aria-label="Fontes do projeto"><h2>Coletar issues</h2><p class="work-muted">Usa os MCPs e o acesso já configurados neste projeto. Informe a origem exata das issues.</p><form @submit.prevent="collect"><label class="work-field">Fonte<select v-model="form.source"><option value="sentry">Sentry</option><option value="kbgen">KBGen</option></select></label><label class="work-field">Instância ou organização<input v-model="form.source_instance" required maxlength="200" placeholder="Identificador da organização" /></label><label class="work-field">Projeto na fonte<input v-model="form.source_project" required maxlength="200" placeholder="Identificador do projeto" /></label><label class="work-field">Consulta (opcional)<input v-model="form.query" maxlength="2000" placeholder="Filtro de issues" /></label><button class="work-button" :disabled="busy || !form.source_instance.trim() || !form.source_project.trim()">{{ busy ? 'Registrando…' : 'Coletar issues' }}</button></form><p v-if="error" class="work-error" role="alert">{{ error }} <button type="button" class="work-button" @click="load">Atualizar</button></p><p v-if="receipt" class="work-muted" role="status">{{ receipt }}</p><ul v-if="collections.length"><li v-for="collection in collections" :key="String(collection.id)"><button class="work-link" @click="inspect(collection.id)">{{ collection.source }} · {{ collection.source_project }} · {{ collection.state ?? collection.status }}</button></li></ul><details v-if="selected" open><summary>Resultado da coleta</summary><pre>{{ JSON.stringify(selected, null, 2) }}</pre></details></section></template>
<style scoped>
.sources-panel{flex-shrink:0;max-height:60%;overflow:auto;padding:20px 24px;border-bottom:1px solid var(--color-line);background:var(--color-panel)}h2{font-size:0.875rem;font-weight:500;margin:0 0 6px}form{display:grid;grid-template-columns:140px minmax(130px,1fr) minmax(130px,1fr);gap:12px;max-width:900px;align-items:end}form>label:nth-child(4){grid-column:1/3}form>button{justify-self:start}ul{padding-left:18px;font-size:0.75rem;line-height:1.8}li button{border:0;background:transparent;font:inherit;text-align:left;cursor:pointer}details{font-size:0.75rem;margin-top:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:0.6875rem;max-height:260px;overflow:auto}@container(max-width:650px){form{grid-template-columns:1fr}form>label:nth-child(4){grid-column:auto}.sources-panel{padding:16px}}
</style>
