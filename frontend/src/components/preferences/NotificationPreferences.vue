<script setup lang="ts">
import { setNotificationPref, notificationPrefs, type NotificationPrefs } from '../../notificationPrefs'
import {
  notificationPermission,
  refreshNotificationPermission,
  requestNotificationPermission,
  sendTestNotification,
} from '../../notifications'

// No "Subagente falhou" here: the session list does not say when a subagent fails (only the open conversation
// does), so nothing would trigger it. Put it back when that information reaches the notifier.
const OPTIONS: Array<{ key: keyof NotificationPrefs; label: string }> = [
  { key: 'permission', label: 'Pedido de permissão' },
  { key: 'question', label: 'Pergunta' },
  { key: 'plan', label: 'Plano para aprovar' },
  { key: 'finished', label: 'Turno concluído' },
]

// The permission can change in the browser's own settings while this screen stays closed.
refreshNotificationPermission()

function ask() {
  void requestNotificationPermission()
}
</script>

<template>
  <div class="flex flex-col gap-7 px-7 py-6" aria-label="Preferências de notificações" role="group">
    <div class="flex flex-col gap-3">
      <h2 class="m-0 font-mono text-xs font-normal tracking-[0.08em] text-fg-muted uppercase">Neste navegador</h2>

      <template v-if="notificationPermission === 'unsupported'">
        <p data-test="notif-unsupported" class="m-0 text-fg-muted">
          Este navegador não oferece notificações do sistema.
        </p>
      </template>

      <template v-else-if="notificationPermission === 'default'">
        <p class="m-0 text-fg-muted">
          O Maestro pode avisar pelo sistema quando uma conversa precisar de você, mesmo com a aba em segundo plano.
          O navegador vai pedir a sua confirmação.
        </p>
        <div>
          <button
            type="button"
            data-test="notif-enable"
            class="h-9 rounded-md bg-primary px-4 font-semibold text-primary-fg hover:bg-primary-soft"
            @click="ask"
          >Ativar notificações</button>
        </div>
      </template>

      <template v-else-if="notificationPermission === 'granted'">
        <div class="flex flex-wrap items-center gap-3">
          <p data-test="notif-granted" role="status" class="m-0 flex items-center gap-1.5 text-primary-soft">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M5 12l5 5 9-10" />
            </svg>
            Notificações ativas neste navegador
          </p>
          <button
            type="button"
            data-test="notif-test"
            class="h-9 rounded-md border border-line-strong px-4 font-medium text-fg hover:bg-card"
            @click="sendTestNotification"
          >Testar</button>
        </div>
      </template>

      <template v-else>
        <div data-test="notif-denied" role="status" class="flex items-start gap-2 text-fg-muted">
          <svg class="mt-0.5 shrink-0 text-secondary" width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M12 3 22 20H2L12 3Z" />
          </svg>
          <p class="m-0">
            As notificações deste site estão bloqueadas no navegador. Para liberar, abra as configurações do site
            (o ícone ao lado do endereço), permita as notificações e volte aqui.
          </p>
        </div>
      </template>
    </div>

    <fieldset class="m-0 flex min-w-0 flex-col gap-3 border-0 p-0">
      <legend class="mb-2 p-0 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Avisar quando</legend>
      <label v-for="option in OPTIONS" :key="option.key" class="flex cursor-pointer items-center gap-2.5">
        <input
          type="checkbox"
          :data-test="`notif-pref-${option.key}`"
          :checked="notificationPrefs[option.key]"
          class="size-4 accent-primary"
          @change="setNotificationPref(option.key, ($event.target as HTMLInputElement).checked)"
        />
        {{ option.label }}
      </label>
    </fieldset>

    <fieldset class="m-0 flex min-w-0 flex-col gap-3 border-0 p-0">
      <legend class="mb-2 p-0 font-mono text-xs tracking-[0.08em] text-fg-muted uppercase">Como</legend>
      <label class="flex cursor-pointer items-center gap-2.5">
        <input
          type="checkbox"
          data-test="notif-pref-onlyWhenHidden"
          :checked="notificationPrefs.onlyWhenHidden"
          class="size-4 accent-primary"
          @change="setNotificationPref('onlyWhenHidden', ($event.target as HTMLInputElement).checked)"
        />
        Só quando o Maestro não estiver em foco
      </label>
      <label class="flex cursor-pointer items-center gap-2.5">
        <input
          type="checkbox"
          data-test="notif-pref-sound"
          :checked="notificationPrefs.sound"
          class="size-4 accent-primary"
          @change="setNotificationPref('sound', ($event.target as HTMLInputElement).checked)"
        />
        Tocar som
      </label>
      <p class="m-0 text-xs text-fg-muted">
        O som é um bipe curto e baixo, só para permissão, pergunta e plano. Vale só neste navegador.
      </p>
    </fieldset>
  </div>
</template>
