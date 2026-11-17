<script setup lang="ts">
import ToggleSwitch from '../ui/ToggleSwitch.vue'
import GroupHeader from '../ui/GroupHeader.vue'
import { setNotificationPref, notificationPrefs, type NotificationPrefs } from '../../notificationPrefs'
import {
  notificationPermission,
  playAlertSound,
  refreshNotificationPermission,
  requestNotificationPermission,
  sendTestNotification,
} from '../../notifications'

type Option = { key: keyof NotificationPrefs; title: string; hint: string; label: string }
type Group = { id: 'needs-you' | 'follow' | 'how'; title: string; options: Option[] }

// No "Subagente falhou" here: the session list does not say when a subagent fails (only the open conversation
// does), so nothing would trigger it. Put it back when that information reaches the notifier.
const GROUPS: Group[] = [
  {
    id: 'needs-you',
    title: 'Precisa de você',
    options: [
      { key: 'permission', title: 'Pedido de permissão', hint: 'O Claude quer rodar um comando ou editar um arquivo.', label: 'Avisar em pedido de permissão' },
      { key: 'question', title: 'Pergunta', hint: 'O Claude parou para perguntar algo.', label: 'Avisar em pergunta' },
      { key: 'plan', title: 'Plano para aprovar', hint: 'Um plano espera a sua aprovação.', label: 'Avisar em plano para aprovar' },
    ],
  },
  {
    id: 'follow',
    title: 'Para acompanhar',
    options: [
      { key: 'finished', title: 'Turno concluído', hint: 'A conversa terminou o que estava fazendo.', label: 'Avisar em turno concluído' },
      { key: 'specialistNotice', title: 'Avisos dos agentes', hint: 'Uma execução de rotina deixou um aviso na Inbox.', label: 'Avisar em avisos dos agentes' },
    ],
  },
  {
    id: 'how',
    title: 'Como',
    options: [
      { key: 'onlyWhenHidden', title: 'Só quando o Maestro não estiver em foco', hint: 'Com a aba à vista, o aviso fica só na tela.', label: 'Só quando o Maestro não estiver em foco' },
      { key: 'sound', title: 'Tocar som', hint: 'Bipe curto e baixo, só para permissão, pergunta e plano.', label: 'Tocar som' },
    ],
  },
]

const noticeClass = 'flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-secondary/50 bg-secondary-tint py-2.5 pr-2.5 pl-3.5 text-sm text-fg'

// The permission can change in the browser's own settings while this screen stays closed.
refreshNotificationPermission()

function ask() {
  void requestNotificationPermission()
}
</script>

<template>
  <div class="flex flex-col gap-5 px-7 py-6" aria-label="Preferências de notificações" role="group">
    <p v-if="notificationPermission === 'unsupported'" data-test="notif-unsupported" class="m-0 text-sm text-fg-muted">
      Este navegador não oferece notificações do sistema.
    </p>

    <div v-else-if="notificationPermission === 'default'" data-test="notif-notice" :class="noticeClass">
      <svg class="shrink-0 text-secondary" width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M12 3 22 20H2L12 3Z" />
      </svg>
      <p class="m-0 min-w-0 flex-1">
        <strong class="font-semibold text-secondary-soft">Ainda não ativadas neste navegador.</strong>
        As escolhas abaixo só passam a valer depois de ativar; o navegador vai pedir a sua confirmação.
      </p>
      <button
        type="button"
        data-test="notif-enable"
        class="h-9 cursor-pointer rounded-lg border-0 bg-secondary px-3.5 text-sm font-semibold whitespace-nowrap text-secondary-fg hover:bg-secondary-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-secondary"
        @click="ask"
      >Ativar notificações</button>
    </div>

    <div v-else-if="notificationPermission === 'denied'" data-test="notif-denied" role="status" :class="noticeClass">
      <svg class="shrink-0 text-secondary" width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M12 3 22 20H2L12 3Z" />
      </svg>
      <p class="m-0 min-w-0 flex-1">
        As notificações deste site estão bloqueadas no navegador. Para liberar, abra as configurações do site
        (o ícone ao lado do endereço), permita as notificações e volte aqui.
      </p>
    </div>

    <p v-else data-test="notif-granted" role="status" class="m-0 flex items-center gap-1.5 text-sm text-primary-soft">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M5 12l5 5 9-10" />
      </svg>
      Notificações ativas neste navegador
    </p>

    <div class="grid items-start gap-x-8 gap-y-6 md:grid-cols-[minmax(0,1fr)_17.5rem]">
      <div class="flex min-w-0 flex-col gap-4">
        <section
          v-for="group in GROUPS"
          :key="group.id"
          data-test="notif-group"
          :data-group="group.id"
          role="group"
          :aria-label="group.title"
        >
          <GroupHeader :title="group.title" />
          <div
            v-for="option in group.options"
            :key="option.key"
            class="flex min-h-13 items-center gap-3.5 border-b border-line py-2"
          >
            <div class="min-w-0 flex-1">
              <div class="text-sm text-fg">{{ option.title }}</div>
              <div class="text-xs text-fg-subtle">{{ option.hint }}</div>
            </div>
            <button
              v-if="option.key === 'sound'"
              type="button"
              data-test="notif-sound-test"
              class="h-8 shrink-0 cursor-pointer rounded-lg border border-line-strong bg-transparent px-3 text-xs font-medium text-fg hover:bg-card focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg-muted"
              @click="playAlertSound"
            >Ouvir</button>
            <ToggleSwitch
              :data-test="`notif-pref-${option.key}`"
              :model-value="notificationPrefs[option.key]"
              :label="option.label"
              @update:model-value="setNotificationPref(option.key, $event)"
            />
          </div>
        </section>
      </div>

      <div class="flex min-w-0 flex-col gap-2.5">
        <h2 class="m-0 font-mono text-[0.65625rem] leading-[1.875rem] font-semibold tracking-[0.08em] text-fg-subtle uppercase">Como vai aparecer</h2>
        <div
          data-test="notif-preview"
          role="group"
          aria-label="Exemplo de aviso"
          class="flex flex-col gap-1 rounded-xl border border-line-strong bg-card px-3.5 py-3 shadow-lg"
        >
          <div class="flex items-center gap-1.5 text-xs text-fg-subtle">
            <svg class="text-primary" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M3 12c2-6 4-6 6 0s4 6 6 0 4-6 6 0" />
            </svg>
            Cláudio Maestro
            <span class="flex-1" />
            agora
          </div>
          <div class="text-sm font-semibold text-fg">Ajustar a busca de projetos</div>
          <div class="text-xs leading-normal text-fg-muted">Pede permissão para rodar um comando.</div>
        </div>
        <p class="m-0 text-xs leading-normal text-fg-subtle">O título é o da conversa e o texto diz o motivo. Clicar abre a conversa.</p>
        <button
          type="button"
          data-test="notif-test"
          :disabled="notificationPermission !== 'granted'"
          aria-describedby="notif-test-hint"
          class="h-8 w-fit cursor-pointer rounded-lg border border-line-strong bg-transparent px-3 text-xs font-medium text-fg hover:bg-card focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg-muted disabled:cursor-default disabled:text-fg-subtle disabled:hover:bg-transparent"
          @click="sendTestNotification"
        >Enviar um teste</button>
        <p id="notif-test-hint" class="m-0 text-xs leading-normal text-fg-subtle">
          <template v-if="notificationPermission === 'default' || notificationPermission === 'denied'">O teste fica disponível depois de ativar. </template>Estas escolhas valem só neste navegador.
        </p>
      </div>
    </div>
  </div>
</template>
