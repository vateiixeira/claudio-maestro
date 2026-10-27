# CTO: ações claras e continuação de execuções

## Objetivo

No primeiro uso real, a coleta do Sentry terminou um turno sem publicar dados e pediu em texto para ajustar um filtro. Não havia decisão estruturada nem permissão pendente; a tentativa permaneceu `waiting`, ocupando capacidade, e a coleta do KBGen ficou `ready`. A tela mostrou "Sua vez", "Aguardando" e "Pronta", sem uma ação de continuação disponível. Avisos internos apareceram como mensagens do usuário. O usuário autorizou melhorar esse fluxo em 27/10/2026.

## Contratos de produto

- Distinguir decisão humana registrada, permissão nativa, continuação sem entrega, fila, execução e incerteza. Não inferir autorização ou tipo de decisão a partir de prosa.
- Dar acesso direto à resposta/continuação de uma tentativa elegível, com destino explícito e confirmação de envio; manter os controles atuais de admissão e nunca retentar envio incerto automaticamente.
- Mostrar a causa comprovada da fila. Sem causa específica conhecida, dizer somente que aguarda início.
- Identificar avisos automáticos por proveniência persistida, nunca por prefixo de texto; conservar os dados para consulta técnica, sem apresentá-los como fala humana.
- O CTO ocioso não exige ação só porque terminou um turno. Decisões e permissões reais continuam em destaque.
- Preservar seleção/lista de conversas do CTO, rotas, temas, acessibilidade e dados de outros trabalhos.

## Escopo e limites

Trabalhar somente nesta worktree. Não modificar dados do projeto 6 nem enviar prompts ao SDK real. Não reiniciar serviços em uso. Não ampliar permissões, transformar texto em aprovação, alterar política de recursos/pool ou redesenhar o protocolo de processos. Sem nova migration, salvo impedimento concreto revisado. Preview em servidor descartável com SDK/GitHub falsos; publicação depende da aprovação do resultado conforme as regras locais.

## Fases

### 1. Contrato e backend de apresentação

- [x] Confirmar DTOs e IDs de mensagens/notificações e definir contrato compartilhado com o frontend.
- [x] Escrever regressões antes do código para resumo por projeto, elegibilidade de continuação e causa de fila.
- [x] Expor dados de apresentação por APIs existentes/adição mínima, sem alterar o envio ou suas garantias.
- [x] Provar origem automática das mensagens por registro persistido, incluindo histórico/reconexão, sem esconder fala humana semelhante.
- [x] Melhorar instruções do CTO/coletor sobre validação de filtros, espera assíncrona e pedidos acionáveis, sem inventar autorização ou acesso.

### 2. Interface de ação

- [x] Testes Vitest antes dos componentes para a situação real: coletor parado, fila e ausência de decisão estruturada.
- [x] Resumo do próximo passo visível e ação de orientação/continuação com destino exato, estado de envio, erro e rascunho preservado.
- [x] Rótulos de fila e espera coerentes, sem falsa obrigação "Sua vez" para CTO ocioso.
- [x] Avisos automáticos separados e recolhidos, com detalhes técnicos acessíveis e histórico humano preservado.
- [x] Preservar navegação entre projetos/tentativas, respostas HTTP antigas, teclado e mobile.


### 3. Integração e verificação

- [x] E2E com cliente falso: coletor interrompe sem entrega, usuário orienta pela nova ação, coleta termina e próximo trabalho avança.
- [x] Casos de decisão estruturada/permissão/incerteza não recebem ação de continuação indevida.
- [x] Verificações apropriadas via `scripts/check.sh`, lint, tipos/build e E2E isolado.
- [x] Revisão independente de qualidade/segurança e rodada visual desktop/mobile.
- [x] CHANGELOG descreve o comportamento entregue.
- [x] Após a aprovação do preview, criar o commit local com o plano e as caixas comprovadas, conforme `CLAUDE.local.md`.
- [x] Preview concreto disponível para aprovação, com dados sintéticos, sem enviar ações nas sessões reais.

## Paralelismo e propriedade

Depois de fixar o contrato, backend e frontend podem implementar em paralelo: arquivos Python/API/prompt e testes backend de um lado, Vue/TypeScript e testes frontend do outro. Nenhum agente altera os arquivos do outro, migrations, lockfiles, plano ou CHANGELOG compartilhados. E2E/build combinados e verificação de integração são sequenciais, com um runner por worktree. Revisores não alteram o repositório; somente o controlador faz staging/commit.

## Evidências verificadas (27/10/2026)

Revisão de código APROVADO, incluindo os ajustes de rascunho, responsividade e Estado em Detalhes. `env -u VTE_VERSION scripts/check.sh` terminou com saída 0: ruff; 5.087 pytest passaram e 4 foram ignorados; 3.304 Vitest; tipos e build. Depois dos ajustes frontend: suíte completa com 3.309 Vitest e build aprovado; último ajuste de rótulo validado por 37 testes direcionados e outro build aprovado. Backend não foi alterado depois do check integral.

O baseline E2E passou em 192 casos e falhou em um por falta de espaço no celular. Esse defeito e o equivalente em 1280×720 foram corrigidos. A rodada final dos quatro specs afetados passou em 11/11 casos, incluindo 1440×900, 1280×720 e 375×720, teclado, menus, rascunhos, fila, proveniência humana/automática e a continuação na mesma tentativa. O último rótulo em Detalhes passou em replay de 1/1 caso. Não afirmar que uma nova rodada integral de 193 casos foi executada após as correções.

Logs: `/tmp/cto-acoes-claras-check.log`, `/tmp/cto-acoes-claras-e2e-final.log` e `/tmp/cto-acoes-claras-e2e-details-final.log`. Capturas finais em `/tmp/cto-acoes-claras-qa/`.

Preview isolado e persistente em `http://localhost:6647/cto?projeto=9`, serviço `claudio-maestro-cto-preview`, SDK/GitHub falsos e dados descartáveis. Cenário pronto: Sentry espera orientação, KBGen está na fila. App de uso e projeto 6 preservados. Nenhum commit, push ou reinício dos serviços de uso nesta tarefa. Aguardar aprovação visual conforme `CLAUDE.local.md`; depois commit com este plano, integração autorizada e limpeza do preview.

Limitação aceita pela revisão: recibos de origem em `app_state` guardam somente até 20 IDs por dispatch, sem conteúdo, e têm retenção indefinida; não houve migration nem mudança de lifecycle.

## Aprovação e integração

O usuário aprovou a publicação e o reinício dos serviços em 27/10/2026 com “pode”. Commit desta tarefa inclui este plano. Integração na `develop` e verificações de funcionamento ficam registradas no diário local ao terminar.
