<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { errorMessage, sendMessage } from '../../api/http'
import type { WorkAttention } from '../../types/work'
const props = defineProps<{ attention: WorkAttention; initiallyOpen?: boolean }>()
const emit = defineEmits<{ sent: []; stale: [] }>()
const eligible = computed(() => props.attention.kind === 'continuation' && props.attention.can_continue && !!props.attention.session_id && !!props.attention.attempt_id)
const destination = computed(() => `${props.attention.work_item_id}:${props.attention.attempt_id}:${props.attention.session_id}`)
const opened = ref(false), draft = ref(''), sending = ref(false), error = ref(''), sent = ref(false)
const pending = new Set<string>()
let alive = true
onBeforeUnmount(() => { alive = false })
const storageKey = (key: string) => `maestro:work-orientation:${key}`
function readDraft(key: string) { try { return sessionStorage.getItem(storageKey(key)) ?? '' } catch { return '' } }
function saveDraft(key: string, value: string) { try { if (value) sessionStorage.setItem(storageKey(key), value); else sessionStorage.removeItem(storageKey(key)) } catch { /* Storage may be unavailable. */ } }
watch(destination, (key) => { opened.value = !!props.initiallyOpen && !!eligible.value; draft.value = readDraft(key); error.value = ''; sent.value = false; sending.value = pending.has(key) }, { immediate: true })
watch(draft, value => saveDraft(destination.value, value), { flush: 'sync' })
async function send() {
  if (!eligible.value || !draft.value.trim() || sending.value || sent.value) return
  const key = destination.value, sessionId = props.attention.session_id!, text = draft.value
  sending.value = true; pending.add(key); error.value = ''
  try {
    const result = await sendMessage(sessionId, text)
    if (!alive) return
    if (result.state === 'error' || result.send_started === false) throw new Error(result.send_started === false ? 'O envio não foi iniciado. Confira o estado da execução.' : 'Não foi possível confirmar o envio. Aguarde a conciliação da execução.')
    const unchanged = readDraft(key) === text
    if (unchanged) saveDraft(key, '')
    if (key !== destination.value) return
    if (unchanged && draft.value === text) draft.value = ''
    sent.value = true; emit('sent')
  } catch (e) {
    if (!alive || key !== destination.value) return
    error.value = errorMessage(e); emit('stale')
  } finally { pending.delete(key); if (alive && key === destination.value) sending.value = false }
}
</script>
<template>
  <section v-if="eligible || sent || opened" class="work-continuation" aria-label="Orientar execução">
    <p v-if="sent" role="status" class="work-note">Orientação enviada à tentativa #{{ attention.attempt_id }}. Acompanhe a execução acima.</p>
    <template v-else>
      <button v-if="!opened" type="button" class="work-button work-primary" @click="opened = true">Orientar execução</button>
      <form v-else @submit.prevent="send">
        <label :for="`orientation-${attention.attempt_id}`">Orientação para {{ attention.title }}, tentativa #{{ attention.attempt_id }}</label>
        <p class="work-muted">Leia a última resposta acima e escreva como o trabalhador deve continuar. A mensagem será enviada somente a esta execução.</p>
        <p v-if="!eligible" role="status" class="work-muted">A execução mudou e não aceita continuação agora. Seu rascunho foi mantido.</p>
        <textarea :id="`orientation-${attention.attempt_id}`" v-model="draft" rows="4" class="work-input" :disabled="sending" autofocus />
        <p v-if="error" role="alert" class="work-error">{{ error }} O rascunho foi mantido. Confira o estado da execução antes de enviar novamente.</p>
        <div class="orientation-actions"><button type="submit" class="work-button work-primary" :disabled="sending || !eligible || !draft.trim()">{{ sending ? 'Enviando…' : 'Enviar orientação' }}</button><button type="button" class="work-button" :disabled="sending" @click="opened = false">Fechar</button></div>
      </form>
    </template>
  </section>
</template>
<style scoped>
.work-continuation{margin-top:18px;min-width:0}label{display:block;font-size:0.8125rem;font-weight:500;overflow-wrap:anywhere}textarea{display:block;width:100%;box-sizing:border-box;min-height:100px;resize:vertical;border:1px solid var(--color-line-strong);background:var(--color-surface);color:var(--color-fg);border-radius:6px;padding:10px;font:inherit;font-size:0.8125rem;line-height:1.6}textarea:focus-visible{outline:2px solid var(--color-primary);outline-offset:2px}.orientation-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
</style>
