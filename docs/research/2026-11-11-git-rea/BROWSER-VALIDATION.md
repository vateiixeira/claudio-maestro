# Validação no navegador — painel Git

Execução em 11/11/2026, Chrome do sistema, Playwright, um worker, backend descartável em `127.0.0.1:6632`. Projetos Histórico Demo, Alterações Demo, Merge Demo e Sincronia Demo; nenhum SDK ou dado pessoal foi usado.

## Resultado observado

- Subconjunto Git: **29 testes passaram em 2,2 minutos** após corrigir as expectativas de atualização explícita do histórico e de feedback acessível ao copiar.
- Comparação: base local e upstream, ambos os sentidos, arquivos e diff, paginação de 30 para 34 commits, persistência da base; SHA e branch de trabalho permaneceram iguais.
- Histórico: reabrir sem revisão nova reutilizou o snapshot, sem GET de log; commit/merge/push/pull mantiveram o snapshot até clicar em atualizar.
- Um repositório abriu automaticamente; recolher Alterações e Commits sobreviveu ao reload.
- Viewports reais de **360, 768 e 1440 px**: painel e menu de branches dentro da largura disponível. Há truncamento por reticências nos nomes em espaços estreitos.
- Exploração manual da comparação: console sem erros ou avisos. Os specs também verificam erros de console.
- Suíte E2E completa: **200 testes passaram em 7,3 minutos**, sem falhas ou testes pulados.

O teste detectou e motivou duas correções: o repositório se recolhia ao ficar em dia após sincronizar; e a rota de um projeto não usava o menu compacto, deixando o painel sem largura em 360 px. Ambos passaram no subconjunto final.

## Medição do navegador

Uma amostra na suíte completa, com HTTP real e Git real no diretório descartável:

| Medida | Observado |
|---|---:|
| GET de detalhes ao abrir | 1 |
| GET de histórico ao abrir | 1 |
| GET adicional de detalhes após preparar | 0 |
| GET adicional de histórico após preparar | 0 |
| Clique em preparar até arquivo aparecer em Preparados | 883 ms |
| Linhas de commits no DOM inicial do Histórico Demo | 30 |

O tempo inclui automação, servidor local e renderização; não é p95 nem demonstra ganho percentual. O debounce foi drenado com o relógio controlado do Playwright depois de medir o tempo até a linha visível. Não foram medidos heap, FPS ou DOM com 200 linhas. O benchmark de subprocessos está em [PERFORMANCE.md](PERFORMANCE.md).

Uma execução anterior recebeu um GET de detalhes extra após alteração externa da fixture. As três execuções seguintes (isolada, subconjunto completo e suíte completa) tiveram zero GET extra. A captura de diagnóstico da execução final mostrou o mesmo `mutation_id` no WebSocket e na resposta do POST. Não se atribuiu ganho ao caso intermitente sem evidência de origem; a instrumentação temporária foi retirada.

## Evidência visual

- [Alterações e commits, com arquivo preparado](screenshots/git-changes-focused.png)
- [Comparação e histórico, painel focado](screenshots/git-panel-focused.png)
- [360 px](screenshots/git-360.png), [768 px](screenshots/git-768.png), [1440 px](screenshots/git-1440.png)
- [Medição HTTP e latência em JSON](screenshots/git-panel-requests.json)
- Temas capturados: Maestro, [Dracula](screenshots/git-theme-dracula.png), [Monokai Pro](screenshots/git-theme-monokai-pro.png), [Machine](screenshots/git-theme-monokai-machine.png), [Octagon](screenshots/git-theme-monokai-octagon.png), [Ristretto](screenshots/git-theme-monokai-ristretto.png), [Spectrum](screenshots/git-theme-monokai-spectrum.png), [Classic](screenshots/git-theme-monokai-classic.png).
- [Ampliação CSS de 200%](screenshots/git-css-zoom-200.png): é `zoom` CSS, **não** zoom nativo do Chrome. Não certifica comportamento de zoom nativo.

As capturas são do resultado implementado. A imagem fornecida do VS Code é referência de composição; não há baseline visual automatizado anterior nem alegação de equivalência pixel a pixel. O arquivo `git-360-shell-limitation.png` registra a falha descoberta antes da correção, não o resultado atual. As capturas e os dados de medição acompanham o relatório no repositório.

## Specs

Criado: `frontend/e2e/git-rea.e2e.ts`.
Atualizados: `git-branches.e2e.ts`, `git-changes.e2e.ts`, `git-commits.e2e.ts`, `git-sync.e2e.ts`.

Comandos executados: `MAESTRO_E2E_PORT=6632 pnpm --dir frontend exec playwright test git-` e `MAESTRO_E2E_PORT=6632 pnpm --dir frontend e2e`.

Ao terminar, o servidor encerrou com SIGTERM; a porta 6632 ficou livre e a pasta temporária `maestro-e2e-fb09ivww` foi removida. Não ficou `.playwright-cli/` na worktree.
