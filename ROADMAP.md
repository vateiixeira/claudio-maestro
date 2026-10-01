# Roadmap do Vini7 Vibing

Acompanha a construção completa do app. É a fonte única do que está feito e do que falta.

Última atualização: 2026-09-30

## Como usar

- Um item só recebe `[x]` depois que os testes dele rodaram e passaram. Anote a data ao lado.
- Ao começar um marco, troque o estado dele na tabela para "Em andamento".
- Trabalho descoberto no caminho entra como item novo, no marco a que pertence.
- Decisões que mudam o rumo vão para a seção "Decisões", com data.

## Visão geral

| Marco | Entrega | Estado | Itens |
|---|---|---|---|
| Preparação | Requisitos, design e viabilidade | Concluído | 6 de 6 |
| 0. Fundação | Backend e frontend no ar em modo de desenvolvimento | Concluído | 6 de 6 |
| 1. Conversa funcionando | Um projeto, uma sessão com streaming e permissões | Concluído | 13 de 13 |
| 2. Multissessão | Colunas, estados e menu lateral | Concluído | 12 de 12 |
| 3. Histórico | Retomada, busca e ocultação | Concluído | 8 de 8 |
| 4. Git | Branches em todas as telas e painel de alterações | Concluído | 8 de 8 |
| 5. Controles | Modelo, raciocínio, modo, imagens, voz, subagentes, perguntas e planos | Concluído | 15 de 15 |
| 6. Acabamento | Erros, robustez e uso diário | Concluído | 50 de 50 |
| 7. Nova navegação | Inbox, Conversas, página única da conversa, nova conversa e Dashboard | Concluído | 27 de 27 |
| 8. Agrupador de sessões | Organizar sessões relacionadas dentro do projeto | Concluído | 11 de 11 |
| 9. Progresso de planos | Etapa atual de cada plano em execução, fixa na tela | Concluído | 11 de 11 |
| 10. Agente de resumos | Resumo em fases de cada conversa em andamento, feito por um agente do app | Concluído | 10 de 10 |
| 11. Tela do projeto e ajustes | Git do projeto, conversa lado a lado, ícone de execução e menus fora do modal | Concluído | 5 de 5 |
| 12. Ajustes de sessões e menu lateral | Em execução no menu, worktree da sessão, Detalhes ajustável e ditado no modal | Concluído | 23 de 23 |
| 13. Comandos e menções | Sugestões de `/` e `@` no campo de mensagem, como na extensão do VSCode, padrões de modelo, raciocínio e modo nas Preferências e copiar blocos de código | Em andamento | 10 de 13 |

Os marcos 0 a 6 formam o MVP, concluído em 2026-09-29. O marco 7 foi pedido pelo usuário em 2026-09-29. O marco 9 foi concluído em 2026-09-29 e o marco 8 em 2026-09-30, ambos a pedido do usuário. Os marcos 11 e 12 começaram e foram concluídos em 2026-09-30, a pedido do usuário, em paralelo ao marco 8. O marco 12 nasceu como um segundo marco 11 numa worktree e foi renumerado ao entrar na main. Ele foi reaberto no mesmo dia por um bug de subagentes e por ajustes no menu lateral. O marco 13 foi pedido em 2026-09-30 e está em andamento junto com o fim do marco 12.

## Preparação

- [x] Levantamento de requisitos (2026-09-28)
- [x] Design visual aprovado (2026-09-28)
- [x] Especificação escrita e aprovada (2026-09-28)
- [x] SDK validado com a assinatura, fora do Docker (2026-09-28)
- [x] Prompt de execução escrito (2026-09-28)
- [x] `CLAUDE.md` e roadmap criados (2026-09-28)

## Marco 0. Fundação

Objetivo: os dois processos sobem na máquina, recarregam ao alterar o código e conversam entre si.

- [x] Estrutura do repositório: `backend/`, `frontend/`, `pyproject.toml`, `.gitignore` (2026-09-28)
- [x] Backend sobe em `127.0.0.1:6660` com recarga automática e responde a uma rota de saúde (2026-09-28)
- [x] Frontend sobe em `127.0.0.1:6600` com recarga automática e proxy para o backend (2026-09-28)
- [x] Testes do backend e do frontend rodam, com um teste de exemplo em cada (2026-09-28)
- [x] Seção de comandos do `CLAUDE.md` corrigida com os comandos reais (2026-09-28)
- [x] Roteiro de teste manual contra o SDK real, seguindo os cuidados do `CLAUDE.md` (2026-09-28)

## Marco 1. Conversa funcionando

Objetivo: criar um projeto, abrir uma sessão, conversar com streaming e responder a um pedido de permissão.

Backend

- [x] Configuração e banco SQLite com migrações (2026-09-28)
- [x] Proteção de `Host` e `Origin`, e validação de caminhos (2026-09-28)
- [x] Projetos: criar, listar, renomear, remover (2026-09-28)
- [x] Navegador de pastas limitado à pasta pessoal (2026-09-28)
- [x] Interface do agente, cliente real sobre o SDK e cliente falso para testes (2026-09-28)
- [x] Conversão das mensagens do SDK em itens de conversa (2026-09-28)
- [x] Sessão ativa: enviar mensagem, interromper, máquina de estados (2026-09-28)
- [x] Fila de permissões: pedir, responder, cancelar ao interromper (2026-09-28)
- [x] WebSocket de eventos e rotas de sessão (2026-09-28)

Frontend

- [x] Estrutura com Vite, Tailwind e as cores e fontes da identidade visual (2026-09-28)
- [x] Menu lateral com projetos e tela de novo projeto (2026-09-28)
- [x] Coluna de sessão: conversa com streaming, blocos de texto, raciocínio, leitura, edição e comando (2026-09-29)
- [x] Cartão de permissão e campo de mensagem com Enter e Ctrl+Enter (2026-09-29)

## Marco 2. Multissessão

Objetivo: acompanhar várias sessões de projetos diferentes ao mesmo tempo.

- [x] Várias sessões ativas no backend, cada uma com seu processo (2026-09-29)
- [x] Remover projeto fecha as sessões ativas dele e resolve pedidos pendentes (2026-09-29)
- [x] Lista de sessões do menu não é sobrescrita por respostas antigas nem por eventos fora de ordem (2026-09-29)
- [x] Desligamento de sessão ociosa após 30 minutos, com religamento automático (2026-09-29)
- [x] Colunas lado a lado, largura ajustável, rolagem horizontal (2026-09-29)
- [x] Layout salvo e restaurado ao reabrir o app (2026-09-29)
- [x] Três estados exibidos: em execução, aguardando você, finalizada (2026-09-29)
- [x] Marcar sessão como finalizada e reabrir (2026-09-29)
- [x] Renomear sessão pela interface, gravando com `rename_session` do SDK para o nome valer também no CLI (2026-09-29)
- [x] Menu lateral com sessões abertas por projeto e contadores (2026-09-29)
- [x] Tela do projeto com sessões nos três blocos (2026-09-29)
- [x] Tela "Todas as sessões" com filtro por projeto (2026-09-29)

## Marco 3. Histórico

Objetivo: continuar no app o trabalho que começou no CLI ou na extensão.

- [x] Índice de sessões sincronizado a partir do histórico (2026-09-29)
- [x] Sessões de repositórios dentro da pasta do projeto entram no projeto (2026-09-29)
- [x] Abrir sessão antiga carrega a conversa sem criar processo (2026-09-29)
- [x] Retomar sessão antiga ao enviar mensagem (2026-09-29)
- [x] Busca no menu lateral por título, resumo e primeiro prompt (2026-09-29)
- [x] Sessões sem atividade há mais de 3 dias ocultas do menu, com contagem (2026-09-29)
- [x] Aviso ao retomar sessão modificada no último minuto por outro processo (2026-09-29)
- [x] Nome dado a uma sessão antes da primeira mensagem aplicado ao CLI depois da primeira conexão (2026-09-29)

## Marco 4. Git

Objetivo: saber em que branch cada repositório está e ver o que o Claude alterou.

- [x] Descoberta de repositórios na pasta do projeto, até 3 níveis (2026-09-29)
- [x] Leitura de branch, inclusive com HEAD solto (2026-09-29)
- [x] Branches no menu lateral, no cabeçalho da sessão, na tela do projeto e no novo projeto (2026-09-29)
- [x] Atualização automática: ao fim de cada turno e a cada 30 segundos (2026-09-29)
- [x] Painel de alterações fechado por padrão, aberto ao clicar em uma edição (2026-09-29)
- [x] Diff da edição clicada e lista de arquivos modificados por repositório (2026-09-29)
- [x] Diff atual de um arquivo contra o último commit (2026-09-29)
- [x] "Abrir no editor" com comando configurável (2026-09-29)

## Marco 5. Controles

Objetivo: tudo o que o CLI permite ajustar em uma sessão, pela interface.

- [x] Lista de modelos vinda do SDK (2026-09-29)
- [x] Troca de modelo com a sessão ativa (2026-09-29)
- [x] Troca de modo de permissão, com confirmação para "Sem perguntas" (2026-09-29)
- [x] Troca de raciocínio por reconexão entre turnos (2026-09-29)
- [x] Campo de mensagem que cresce até 40% da coluna (2026-09-29)
- [x] Colar e arrastar imagens, com miniatura e remoção (2026-09-29)
- [x] Perguntas do Claude respondidas pela interface (2026-09-29)
- [x] Aprovação de plano pela interface (2026-09-29)
- [x] Blocos de busca e lista de tarefas (2026-09-29)
- [x] Subagentes visíveis na sessão: um cartão por subagente com tipo, descrição e estado (rodando, concluído, com erro), e as ações dele (ferramentas, edições, comandos) aparecendo em tempo real dentro do cartão. Vale também para subagentes em segundo plano (2026-09-29)
- [x] Cartão genérico para ferramentas e MCPs sem bloco próprio (2026-09-29)
- [x] Saídas longas truncadas em 200 linhas (2026-09-29)
- [x] Sessões do CLI em tempo real: observar `~/.claude/projects` e atualizar índice, menu e colunas abertas em até 1 s após cada mudança, sem esperar a sincronização de 60 s (2026-09-29)
- [x] Raciocínio visível enquanto o Claude pensa: bloco aberto durante o streaming, recolhido ao terminar, com indicação de tempo. Só em sessões conduzidas pelo app; o CLI não grava o texto do raciocínio no arquivo da sessão (2026-09-29)
- [x] Ditado por voz: botão de microfone no campo de mensagem que transcreve a fala em texto, para revisar antes de enviar (tecnologia a definir, ver "Pontos em aberto") (2026-09-29)

## Marco 6. Acabamento

Objetivo: o app aguenta o uso diário sem surpresas.

- [x] Sessão nova do app começa no `defaultMode` do `~/.claude/settings.json` do usuário (o SDK não herda o `auto`) (2026-09-29)
- [x] Mensagem enviada durante um turno ou com permissão pendente não se perde (2026-09-29)
- [x] Recarregar a página no meio de uma resposta preserva texto e permissão pendente (2026-09-29)
- [x] Salto de `seq` nos eventos de uma conversa recarrega o retrato (evento perdido entre retrato e abertura do WebSocket) (2026-09-29)
- [x] Navegador de pastas ignora respostas fora de ordem (2026-09-29)
- [x] Layout restaurado de novo na reconexão quando a primeira leitura falhou (2026-09-29)
- [x] Sessão criada em uma aba aparece nas outras e não some por listagem em andamento (2026-09-29)
- [x] Remover projeto espera conexões em andamento das sessões dele (2026-09-29)
- [x] Fechamentos de cliente disparados por cancelamento durante a conexão passam pelo mesmo controle de descarte (2026-09-29)
- [x] Aviso de atividade externa sem falso positivo depois de reinício do backend ou de falha do processo (2026-09-29)
- [x] Limite total de tamanho do retrato, incluindo entradas de ferramentas e leitura de arquivos de sessão enormes (2026-09-29)
- [x] Checagem de modificação de sessão por `stat` do arquivo em vez de listar a pasta; custo da sincronização com milhares de sessões (2026-09-29)
- [x] Aviso para transcrição corrompida e resumo de compactação exibido como aviso, não como mensagem do usuário (2026-09-29)
- [x] Nova tentativa de carregar a conversa depois de uma falha (2026-09-29)
- [x] Aviso na interface quando um projeto passa de 50 repositórios (2026-09-29)
- [x] Preservar nomes dados no app antes da migração do marco 3 (2026-09-29)
- [x] Prévia de repositórios na tela de novo projeto segue a mesma descoberta do projeto (3 níveis, pastas ignoradas) (2026-09-29)
- [x] Botão "Escolher pasta…" no novo projeto abre o seletor de pastas nativo do sistema (zenity no GNOME), com o navegador de pastas atual como alternativa (2026-09-29)
- [x] Tela de preferências: comando do editor, dias para ocultar sessões (2026-09-29)
- [x] Arquivos modificados na sessão incluem edições fora das últimas 500 mensagens do histórico (2026-09-29)
- [x] "HEAD solto" indicado também no navegador de pastas (2026-09-29)
- [x] Espera por vaga de processo git não conta no tempo limite de 5 s; diff de arquivo que some durante a leitura dá erro legível (2026-09-29)
- [x] Observador do CLI: coluna recarrega em até 1 s (hoje 2 s) e leitura só da sessão alterada, sem listar a pasta inteira (2026-09-29)
- [x] Interromper também para subagentes em segundo plano (2026-09-29)
- [x] Duas abas abertas ficam consistentes; resposta duplicada é recusada sem erro (2026-09-29)
- [x] Processo do Claude morto, CLI ausente e login expirado mostram erro legível (2026-09-29)
- [x] Limite da assinatura atingido mostra o horário de liberação (2026-09-29)
- [x] Projeto com pasta apagada aparece como indisponível (2026-09-29)
- [x] Caminhos com espaços, acentos e links simbólicos para fora da pasta pessoal (2026-09-29)
- [x] Revisão de acessibilidade: teclado, contraste e foco (2026-09-29)
- [x] Fontes servidas pelo próprio app; hoje vêm do Google Fonts e dependem de internet (2026-09-29)
- [x] Chat em turnos: sua mensagem abre o turno, trilho com um nó por tipo de elemento e resumo no fim do turno (desenho: https://claude.ai/artifact/B6MJz27qejqyqorFhskF11) (2026-09-29)
- [x] Texto das respostas acompanha a largura da coluna (hoje limitado a 580 px) (2026-09-29)
- [x] Botão para copiar a resposta inteira em markdown (2026-09-29)
- [x] Raciocínio durante o streaming mostra só as 4 últimas linhas, acompanhando o texto, com opção de expandir (2026-09-29)
- [x] Faixa de subagentes junto ao campo de mensagem: aparece enquanto houver subagente rodando (inclusive em segundo plano) e some quando todos terminam. Lista cada um com tipo, descrição, estado (rodando, concluído, com erro, parado) e última ação; o clique leva ao cartão na conversa. Com mais de 3, mostra um resumo ("3 rodando, 1 concluído") que abre a lista ao clicar (2026-09-29)
- [x] Porcentagem de contexto usada na coluna da sessão, junto aos controles: atualizada ao fim de cada turno com `get_context_usage()` do SDK; sessões sem cliente conectado usam o `usage` da última resposta do histórico (2026-09-29)
- [x] Lista de modelos guardada no SQLite, usada ao reiniciar o backend e atualizada até 3 vezes por dia (2026-09-29)
- [x] "Permitir" e "Negar" direto nos cartões "Aguardando você" da tela "Todas as sessões", como no desenho aprovado (2026-09-29)
- [x] Ações seguidas do chat viram um grupo, aberto enquanto o turno roda e recolhido depois (2026-09-29)
- [x] Saídas longas no chat limitadas a 8 linhas e barra fixa do turno com navegação entre turnos (2026-09-29)
- [x] Aviso de mais de 50 repositórios também atualizado pelo evento `project.git`, sem recarregar (2026-09-29)
- [x] Modo "Automático" recusado pelo modelo (o haiku não tem modo automático) não derruba a sessão: o modo volta ao anterior com aviso legível (2026-09-29)
- [x] Botão "Parar subagentes" na faixa de subagentes, também com a sessão ociosa (achado da revisão do marco 6: o "Interromper" some quando o turno acaba) (2026-09-29)
- [x] Sessão não fica ociosa entre o fim de um turno autônomo e a resposta a uma mensagem enviada durante ele (2026-09-29)
- [x] Leitura do contexto não segura o fim do turno nem deixa pedido pendurado no SDK; porcentagem e tokens na mesma base (2026-09-29)
- [x] Seletor de pastas fechado quando a aba desiste do pedido; mensagem de login expirado só com as frases específicas do CLI (2026-09-29)
- [x] Prévia de repositórios aborta pedidos anteriores; tokens do contexto acessíveis; nova tentativa na coluna com falha de carga (2026-09-29)
- [x] Espera pelo turno seguinte ao autônomo encerrada pelo `init` e prévia de repositórios cancelada quando a aba desiste (achados da segunda revisão do marco 6) (2026-09-29)
- [x] Testes intermitentes estabilizados: `composerExtras.spec.ts` (frontend) e `test_controls.py::test_autonomous_turn_then_user_turn` (backend) (2026-09-29)

## Marco 7. Nova navegação

Objetivo: trocar as colunas de sessões lado a lado por telas no estilo do Paperclip. Cada conversa do Claude Code corresponde a uma "task" de lá.

Pedido pelo usuário em 2026-09-29, depois de analisar o Paperclip (orquestrador de agentes) rodando localmente. Só a disposição e os componentes de layout vêm de lá; nada de agentes, rotinas ou orçamento.

- Spec: `docs/superpowers/specs/2026-09-29-nova-navegacao-design.md`
- Plano: `docs/superpowers/plans/2026-09-29-nova-navegacao.md`

- [x] Resumo da sessão com última ação, tipo do pedido pendente e data de finalização (2026-09-29)
- [x] Rotas de marcar várias conversas como lidas e de atividade por dia (2026-09-29)
- [x] Linha de conversa e regras de Inbox e grupos por data (2026-09-29)
- [x] Corpo da conversa extraído para um componente próprio (2026-09-29)
- [x] Painel Detalhes com propriedades, alterações e diff (2026-09-29)
- [x] Página única da conversa, com contexto no compositor só a partir de 80% (2026-09-29)
- [x] Menu lateral com entradas fixas, projetos e recentes, e contador no título da aba (2026-09-29)
- [x] Telas de Inbox e Conversas (2026-09-29)
- [x] Modal de nova conversa com rascunho e atalho `C` (2026-09-29)
- [x] Dashboard com conversas ativas, números e gráfico de 14 dias (2026-09-29)
- [x] Página do projeto com a linha de conversa (2026-09-29)
- [x] App abre na Inbox e o código de colunas sai (2026-09-29)
- [x] Indicador de conexão no rodapé do menu, como pede a spec (achado da revisão da tarefa 7) (2026-09-29)
- [x] Correções da revisão do marco: conversa esquecida ao sair, cabeçalho e corpo reiniciados ao trocar de conversa, `finished_at` zerado ao reabrir por envio, estados de carregamento e erro, página sem rolagem extra, linhas alinhadas e foco visível (2026-09-29)
- [x] Bloco "Agora" do Dashboard limitado a 6 cartões, com pedidos pendentes primeiro e link para a Inbox (decisão do usuário) (2026-09-29)
- [x] Recentes do menu só com conversas abertas na página, sem contar "marcar como lida" (decisão do usuário) (2026-09-29)

Pendências da revisão do marco 7 e sugestões que sobraram das revisões do marco 6:

- [x] Ações escondidas da linha de conversa não recebem toque (`pointer-events-none` enquanto invisíveis), e o botão de copiar resposta aparece em tela sem mouse (2026-09-29)
- [x] Esc da gaveta de Detalhes em tela estreita não dispara junto com outros Esc (modal, renomear, menu ⋯, busca) (2026-09-29)
- [x] Sair de uma conversa antes do retrato chegar não a devolve ao store sem inscrição; "Tentar de novo" desabilitado enquanto recarrega (2026-09-29)
- [x] Modal de nova conversa: anexar imagem, soltar arquivo e miniaturas; título e opções preservados se o PATCH falhar depois de criar; atalho `C` não abre por cima de outros diálogos (2026-09-29)
- [x] `POST /api/sessions/seen` grava todas as sessões numa transação, fora do loop de eventos (2026-09-29)
- [x] Rota `PUT /api/state/layout` sem cliente removida (ou volta a ter uso) (2026-09-29)
- [x] Comando do editor nas preferências valida argumento vazio no navegador, com mensagem própria (2026-09-29)
- [x] Teste intermitente de imagem arrastada em `ConversationThread.spec.ts` estabilizado (2026-09-29)
- [x] Modal de nova conversa com sessão já criada: fechar ou descartar leva à conversa criada com o rascunho no campo de mensagem, e o modal não fecha durante o envio (achado bloqueante da revisão das pendências) (2026-09-29)
- [x] Soltar no modal só intercepta arquivos; "Tentar de novo" mantém o foco; anexos simultâneos respeitam os limites; aviso de que imagens não ficam no rascunho; Esc de renomear no projeto segue o contrato (2026-09-29)
- [x] `mark_seen_many` aplica na memória exatamente o valor gravado no banco (2026-09-29)

## Marco 8. Agrupador de sessões

Objetivo: juntar sessões relacionadas dentro de um projeto, para enxergar o trabalho como um conjunto.

Caso de uso que motivou: uma sessão gera um prompt, e esse prompt é executado em uma sessão nova. As duas pertencem ao mesmo trabalho, mas hoje apareceriam soltas na lista.

Pedido pelo usuário em 2026-09-28. Só começa depois do MVP completo e funcionando.

- Spec: `docs/superpowers/specs/2026-09-30-agrupador-de-sessoes-design.md`
- Plano: `docs/superpowers/plans/2026-09-30-agrupador-de-sessoes.md`

O agrupador existe só no banco do backend. O Claude e o CLI não sabem dele, e o histórico em `~/.claude/projects` não muda.

- [x] Tabela de agrupadores no SQLite, ligada ao projeto, e vínculo da sessão com o agrupador (2026-09-30)
- [x] Criar agrupador dentro de um projeto (2026-09-30)
- [x] Renomear agrupador (2026-09-30)
- [x] Remover agrupador; as sessões dele voltam a ficar soltas e não são apagadas (2026-09-30)
- [x] Mover sessão para um agrupador, trocar de agrupador e tirar do agrupador (propriedade em Detalhes) (2026-09-30)
- [x] Criar sessão nova já dentro do agrupador de uma sessão aberta (2026-09-30)
- [x] Menu lateral: cada projeto vira uma árvore recolhível com seus agrupadores e as sessões ativas deles (2026-09-30)
- [x] Tela do projeto mostra os agrupadores em cima e as sessões sem agrupador embaixo (2026-09-30)
- [x] Etiqueta do agrupador na linha de conversa e filtro por agrupador na tela Conversas (2026-09-30)
- [x] Busca de sessões também encontra pelo nome do agrupador (2026-09-30)
- [x] Sessão que a sincronização muda para um projeto aninhado sai do agrupador do projeto antigo, e a tela do projeto mostra como solta a sessão de agrupador desconhecido (achado bloqueante da revisão do marco 8) (2026-09-30)

Decidido no desenho (2026-09-30): uma sessão fica em no máximo um agrupador; o agrupador tem só nome, sem cor; o menu mostra só os agrupadores, com as sessões ativas, e o agrupador sem sessão ativa fica numa linha apagada; a tela Conversas continua por data, com etiqueta e filtro.

Sugestões da revisão do marco 8 deixadas para depois: agrupadores só recarregam na reconexão se os projetos carregarem; trava contra Enter duplo e foco depois do Esc ao criar ou renomear agrupador; criar agrupador por Detalhes cria outro ao tentar de novo quando mover falha; `aria-label` da seta do agrupador no menu; sessão aberta perde o destaque com o agrupador recolhido; estado recolhido não sincroniza entre abas; comparação de nome com NFKD iguala formas de compatibilidade.

## Marco 9. Progresso de planos

Objetivo: saber, sem perguntar ao Claude, em que etapa está cada sessão que executa um plano.

Caso de uso que motivou: um plano de implementação com 15 tarefas roda por muito tempo, e o Claude não diz em qual tarefa está, embora controle isso internamente.

Pedido pelo usuário em 2026-09-28. Só começa depois do MVP completo e funcionando.

- Spec: `docs/superpowers/specs/2026-09-29-progresso-de-planos-design.md`

Fonte dos dados: o arquivo do plano em `docs/superpowers/plans/`. Uma regra no `~/.claude/CLAUDE.md` do usuário manda quem orquestra marcar todas as caixas de uma tarefa quando ela é concluída.

- [x] Regra de marcar a tarefa concluída no plano, no `~/.claude/CLAUDE.md` do usuário (2026-09-29)
- [x] Leitura do plano: tarefas por `### Tarefa N`, concluída com todas as caixas marcadas, tarefa atual, cache por data de modificação (2026-09-29)
- [x] Vínculo automático da conversa ao último plano lido ou editado, ao vivo, pelo observador do CLI e na retomada; guardado no SQLite (2026-09-29)
- [x] Progresso no resumo da sessão, atualizado ao editar o plano, ao fim do turno e numa varredura de 30 s (2026-09-29)
- [x] Rotas para listar planos do projeto, vincular e desligar (2026-09-29)
- [x] Faixa fixa na página da conversa com tarefa atual, barra e lista expansível (2026-09-29)
- [x] Plano em Detalhes: trocar, desligar e religar o automático (2026-09-29)
- [x] Selo "4/12" na linha de conversa e tarefa atual no bloco "Agora" do Dashboard (2026-09-29)
- [x] Conversa do CLI no meio de um turno aparece como em andamento (sinal de turno aberto, inclusive com subagente rodando), com evento também para conversas fora de memória (achado bloqueante da revisão do marco 9) (2026-09-29)
- [x] Leitura de plano recusa arquivo especial e lê no máximo o limite; cabeçalhos de tarefa com qualquer separador; caminho relativo recusado no vínculo; subagentes do CLI contam para o vínculo (2026-09-29)
- [x] Tooltip do selo visível, lista da faixa recarrega ao trocar de plano, contraste do estado parado (2026-09-29)

Decidido no desenho (2026-09-29): a fonte é o arquivo do plano com a regra de marcação; vínculo automático com ajuste manual; tarefa inteira, sem "em andamento"; conversa parada mostra o progresso apagado, e finalizada ou plano 100% só em Detalhes.

Sugestões da revisão do marco 9 deixadas para depois: cercas de código de tipos diferentes no leitor; cache e locks de plano sem limite; `GET /api/sessions/{id}/plan` com efeito colateral; `auto_plan` emite sem mudança; observador carrega a sessão mesmo com vínculo manual ou desligado; varredura não revalida o caminho guardado; Tab não fecha o aviso de lista vazia; desligar o automático antes de haver plano.

## Marco 10. Agente de resumos

Objetivo: saber, sem reler a conversa, o que cada sessão em andamento está fazendo, em quais fases e o que falta, inclusive em sessões longas com várias features.

Pedido pelo usuário em 2026-09-30.

- Spec: `docs/superpowers/specs/2026-09-30-agente-de-resumos-design.md`

Um agente único do app, sem ferramentas, lê a conversa de forma incremental com uma chamada curta do SDK por sessão. O resumo fica só no SQLite; o histórico e os arquivos dos projetos não mudam.

- [x] Configuração do agente em `app_state` e tabelas `session_digests` e `digest_runs` (2026-09-30)
- [x] Leitura incremental do `.jsonl` por cursor e condensação do trecho (2026-09-30)
- [x] Interface `DigestModel`, cliente real sobre o SDK e cliente falso (2026-09-30)
- [x] Mesclagem que congela fases concluídas e valida o selo "Plano concluído" (2026-09-30)
- [x] Agendador: elegibilidade, uma sessão por vez, lock, fila de pedidos manuais, parada por erro e limite (2026-09-30)
- [x] Rotas de configuração, disparo, registro e resumo por sessão, com eventos no WebSocket (2026-09-30)
- [x] Sessões do agente apagadas com `delete_session` e ignoradas pelo índice do histórico (2026-09-30)
- [x] Aba "Agente de resumos" nas Preferências, com registro das passadas e "Rodar agora" (2026-09-30)
- [x] Seção "Resumo" em Detalhes com fases, selo e "Resumir agora" (2026-09-30)
- [x] Frase curta do resumo na linha de conversa (2026-09-30)

Decidido no desenho (2026-09-30): o agente só lê e resume; "plano concluído" é um selo no app, sem tocar o arquivo; instruções extras em texto livre, sem ferramentas; padrão Sonnet 5.5 com raciocínio médio; passada a cada 10 min, mínimo de 10 mensagens novas, teto de 30 min com turno aberto, janela de 3 dias; fases concluídas congeladas.

Concluído em 2026-09-30, com aprovação da revisão do marco depois de uma rodada de correções: login expirado passa a parar a passada, o agente roda com `strict_mcp_config` (verificado no SDK real: só a ferramenta interna `StructuredOutput`, nenhum servidor MCP), e uma fase nova com o título de uma fase concluída não some mais na mesclagem. Teste manual contra o SDK real (`scripts/digest_smoke.py`, haiku): duas leituras da mesma sessão, a incremental manteve a fase anterior, nenhuma sessão ficou em `~/.claude/projects`. Não conferido no navegador.

Deixado para depois (achados menores das revisões): marcadores de login procurados também no texto do modelo podem parar a passada por engano numa conversa que cita "Please run /login" e falha na saída estruturada; cancelamento durante o fechamento normal da passada grava o fim um instante depois; `refreshStatus` sem guarda de ordem; `finish_run` fora de transação; limites do prompt fixo escritos à mão; `_digest_briefs` não é limpo ao apagar sessão; `aria-controls` das abas e teclas Home/End.

## Marco 11. Tela do projeto e ajustes

Objetivo: ver o estado git de cada repositório do projeto e abrir conversas sem sair da tela do projeto, com dois ajustes de uso diário.

Pedido pelo usuário em 2026-09-30. Feito na worktree `.claude/worktrees/tela-projeto`, branch `tela-projeto`, a partir da `main`. Design curto aprovado na conversa, sem spec.

- [x] Menus de opção (`OptionMenu`) desenhados fora do modal, com posição calculada e rolagem própria (2026-09-30)
- [x] Ícone de "em execução" trocado por um arco girando, parado com movimento reduzido (2026-09-30)
- [x] Backend: upstream, ahead/behind, arquivos alterados com +/- e últimos commits por repositório (2026-09-30)
- [x] Tela do projeto: estado git de cada repositório, arquivos com diff ao clicar e últimos commits (2026-09-30)
- [x] Tela do projeto dividida: conversa aberta ao lado pela URL (`?sessao=`), divisória arrastável (2026-09-30)

Decidido no desenho (2026-09-30): o app não roda `git fetch`, então "para baixar" reflete o último fetch; abaixo de 1200px o clique abre a conversa inteira; o ícone novo vale em todas as listas.

Concluído em 2026-09-30, com aprovação da revisão do marco. A revisão pediu duas correções: menus que fechavam com a rolagem da conversa, e a tela do projeto que não se atualizava quando um turno editava um arquivo já modificado. O fim de turno agora sempre avisa a tela, e ela ganhou o botão "Atualizar".

Deixado para depois: conversas do CLI não avisam a tela do projeto no fim do turno (o `CliWatcher` não conhece o projeto da sessão), então elas dependem da checagem periódica e do botão "Atualizar"; conversa nova criada pela tela do projeto abre em tela cheia, não ao lado (decisão do usuário); `git config` extra antes de cada `run_git`; menu preso a um botão cortado por um ancestral com `overflow`.

## Marco 12. Ajustes de sessões e menu lateral

Objetivo: enxergar o que roda (inclusive no terminal) e onde cada sessão trabalha, com ajustes de uso diário no menu lateral, no Detalhes e no modal.

Pedido pelo usuário em 2026-09-30. Feito na worktree `.claude/worktrees/melhorias-ui-sessoes`, em paralelo ao marco 8.

- Spec: `docs/superpowers/specs/2026-09-30-ajustes-sessoes-menu-lateral-design.md`
- Plano: `docs/superpowers/plans/2026-09-30-ajustes-sessoes-menu-lateral.md`

- [x] Detectar a worktree atual pela transcrição (`worktree.py`) (2026-09-30)
- [x] Colunas de worktree, branch e pasta do histórico na sessão (2026-09-30)
- [x] Conversa do CLI no meio de um turno aparece como "Em execução" (2026-09-30)
- [x] Indexar sessões guardadas nas pastas das worktrees (2026-09-30)
- [x] Ler o histórico pela pasta certa e retomar a sessão na worktree (2026-09-30)
- [x] Worktree e branch no cabeçalho, no Detalhes e na lista (2026-09-30)
- [x] Renomear só pelo clique no título (2026-09-30)
- [x] Largura ajustável do painel Detalhes (2026-09-30)
- [x] Progresso do plano no painel Detalhes (2026-09-30)
- [x] Menu lateral com "Em execução", sigla do projeto e Recentes em ordem estável (2026-09-30). A sigla e a ordem estável foram substituídas depois, nos itens abaixo
- [x] Nome do projeto no lugar da sigla no menu lateral (2026-09-30)
- [x] Menu lateral 20% mais largo (2026-09-30)
- [x] Recentes sem as sessões finalizadas (2026-09-30)
- [x] Recentes lista todas as conversas não finalizadas pela última interação, sem lista guardada no navegador; substitui a ordem estável (decisão do usuário) (2026-09-30)
- [x] Ditado no modal de nova conversa (2026-09-30)
- [x] Retomada de sessão movida para worktree conferida contra o SDK real (2026-09-30)
- [x] Sessão do app ociosa com subagente em segundo plano conta como "Em execução" no estado exibido (menu lateral, Inbox e Dashboard), com `subagents_running` no resumo da sessão e evento ao começar e terminar (bug relatado pelo usuário em 2026-09-30) (2026-09-30)
- [x] Sessão do CLI com subagente em segundo plano depois do `end_turn` da cadeia principal conta como "Em execução": `turn_open` hoje só considera a escrita do subagente quando a cadeia principal não decide nada, e o `end_turn` costuma vir depois do subagente terminar, então exige comparar a ordem de escrita entre os arquivos. Resolvido com estado próprio por arquivo de subagente (aberto até o `end_turn` dele), sem comparar a ordem de escrita; a interrupção na cadeia principal zera os subagentes (2026-09-30)
- [x] Subagente do CLI que morre sem `end_turn` deixa de contar como aberto depois de `CLI_TURN_STALE_SECONDS` sem escrever (bloqueante da revisão do marco em 2026-09-30) (2026-09-30)
- [x] Fim de subagente do app seguido de turno autônomo não pisca "Aguardando você" na Inbox (achado da revisão do marco em 2026-09-30). Janela de 3 s (`SUBAGENT_END_GRACE_SECONDS`) em que a sessão segue "Em execução" esperando o turno autônomo (2026-09-30)
- [x] Apagar do navegador a chave antiga de Recentes, que ficou órfã com a remoção de `recentConversations.ts` (achado da revisão do marco em 2026-09-30) (2026-09-30)
- [x] Spec e plano do marco anotam a troca da sigla pelo nome do projeto e a largura nova do menu lateral (achado da revisão do marco em 2026-09-30) (2026-09-30)
- [x] Nova revisão do marco pelo `milestone-reviewer`, depois dos itens reabertos (2026-09-30)

## Marco 13. Comandos e menções

Objetivo: sugestões de `/` (comandos) e `@` (arquivos e pastas) no campo de mensagem, com o mesmo comportamento da extensão do VSCode.

Pedido pelo usuário em 2026-09-30. Feito na worktree `.claude/worktrees/pendencias-12-13`, junto com o fim do marco 12.

- Plano: `docs/superpowers/plans/2026-09-30-comandos-e-mencoes.md`

- Spec: `docs/superpowers/specs/2026-09-30-comandos-e-mencoes-design.md`

- [x] `settings` em `AgentOptions` e no cliente do SDK (2026-09-30)
- [x] Catálogo de comandos e rotas `/commands` (2026-09-30)
- [x] Busca de arquivos e rotas `/files` (2026-09-30)
- [x] Funções puras de sugestão (`suggestions.ts`) (2026-09-30)
- [x] Composable e `SuggestionMenu`, com o menu `/` (2026-09-30)
- [x] Menu `@` com pastas (2026-09-30)
- [x] Integração no campo da conversa (2026-09-30)
- [x] Integração no modal de nova conversa (2026-09-30)
- [ ] Realce das menções e dica de argumentos (`MentionMirror`)
- [x] Comando como balão no histórico (2026-09-30)
- [ ] Verificação manual contra o SDK real e no app
- [ ] Preferências com modelo, raciocínio e modo padrão das novas conversas: o que estiver salvo lá vale para toda sessão nova, no campo da conversa e no modal (pedido do usuário em 2026-09-30, fora da spec de comandos; substitui a decisão de 2026-09-29 de herdar o modo padrão do CLI quando houver valor salvo)
- [x] Botão de copiar em cada bloco de código das respostas do Claude e do plano (pedido do usuário em 2026-09-30, fora da spec de comandos) (2026-09-30)

## Fora do MVP

Ideias registradas para depois. Não entram sem decisão do usuário.

- Terminal embutido
- Editor de código e árvore de arquivos
- Tema claro
- Busca no texto das mensagens
- Commit, push e troca de branch pela interface
- Indicador de consumo dos limites da assinatura
- Agrupar projetos no menu (diferente do agrupador de sessões, que é o marco 8)
- Execução em Docker
- Manter o app sempre ativo, iniciando junto com a máquina
- Internacionalização (i18n) da interface em português do Brasil e inglês (pedido do usuário em 2026-09-30)

## Pontos em aberto

| Ponto | Situação |
|---|---|
| Docker | Adiado. Exigiria rodar o Claude dentro do container, com as pastas montadas no mesmo caminho do host. Não testado |
| Mesma sessão aberta no app e no CLI ao mesmo tempo | Risco de embaralhar o histórico. O app só avisa |
| O que o SDK entrega sobre subagentes | Verificado em 2026-09-29; ver "Fatos verificados para o marco 5" no prompt de construção |
| Usar o Vibing no próprio repositório | O backend roda com recarga automática em `backend/`. Uma edição do Claude nessa pasta reinicia o backend e derruba todas as sessões. Evitar ou rodar sem `--reload` nesse caso |
| Tecnologia do ditado por voz | Decidido em 2026-09-29: reconhecimento do navegador (Chrome/Edge). O áudio vai ao serviço de reconhecimento do navegador |
| Variáveis `CLAUDE*` herdadas ao iniciar o SDK | O teste passou removendo-as. Não se sabe se falha com elas |
| Conversa do CLI ativa aparece como "Aguardando você" | Decidido em 2026-09-30: `cli_running` passa a contar como "Em execução" no estado exibido, na Inbox, no Dashboard e no menu lateral (marco 12) |
| Contagem de turnos em casos raros | Se o CLI juntar duas mensagens num turno só, ou mandar um `init` por outro motivo logo depois de um turno autônomo, a conversa fica em "rodando" até o próximo turno. Nunca observado |
| Painel Alterações em sessões de worktree | Visto na revisão do marco 12 (2026-09-30): arquivos editados numa worktree ficam no grupo do repositório principal (branch errado, diff como arquivo novo), e worktrees fora da pasta do projeto caem no grupo sem repositório e não abrem no editor. Precisa incluir as worktrees ligadas como donas possíveis e aceitar esses caminhos em `/diff` e no editor |
| Janela depois do fim de um subagente do app | 3 s (`SUBAGENT_END_GRACE_SECONDS`) sem medição contra o CLI real. Se o turno autônomo demorar mais, o "Aguardando você" volta a piscar; ajustar o valor se isso aparecer no uso |
| Troca de raciocínio durante subagente | Visto na revisão do marco 12 (2026-09-30): se o raciocínio muda enquanto um subagente roda e o CLI não abre turno depois que ele termina, a reconexão com o valor novo só acontece no próximo turno. Comportamento anterior ao marco |
| "Em execução" preso depois de o CLI morrer | Um CLI morto no meio do turno, ou parado pedindo permissão no terminal, conta como "Em execução" por até 20 minutos (`CLI_TURN_STALE_SECONDS`). Desde o marco 12 isso aparece na Inbox, no Dashboard e no menu lateral |
| Retomada de sessão movida para worktree | Conferido contra o SDK real em 2026-09-30: a transcrição movida é lida com `directory` na worktree, e a retomada com `cwd` na worktree mantém o id e continua gravando no mesmo arquivo |

## Decisões

| Data | Decisão |
|---|---|
| 2026-09-28 | Backend em Python com FastAPI; frontend em Vue 3 |
| 2026-09-28 | Um `ClaudeSDKClient` por sessão ativa, dentro do backend |
| 2026-09-28 | Login de assinatura existente, sem API key |
| 2026-09-28 | Projeto é uma pasta, que pode conter vários repositórios |
| 2026-09-28 | SQLite só para metadados; conversas ficam em `~/.claude/projects` |
| 2026-09-28 | Sem login nem senha; acesso só por localhost |
| 2026-09-28 | Layout em colunas; painel de alterações abre só ao clicar em uma edição (substituído pela nova navegação do marco 7) |
| 2026-09-28 | Visual escuro, verde como primária e laranja como secundária |
| 2026-09-28 | Monolito com backend e frontend no mesmo repositório |
| 2026-09-28 | Docker adiado; execução direto na máquina, em modo de desenvolvimento |
| 2026-09-28 | Frontend na porta 6600 e backend na 6660. As portas 66 e 666 foram descartadas porque o Linux as reserva ao root |
| 2026-09-28 | Planejamento em uma sessão, execução em outra |
| 2026-09-28 | Renomear sessão entra no MVP, usando a função do SDK |
| 2026-09-28 | Agrupador de sessões vira o marco 7, depois do MVP, guardado só no banco do backend |
| 2026-09-28 | Ditado por voz entra no MVP, no marco 5 |
| 2026-09-28 | Ações de subagentes visíveis na sessão entram no MVP, no marco 5 |
| 2026-09-28 | Progresso de planos vira o marco 8, depois do MVP |
| 2026-09-29 | Sessões do CLI atualizadas em tempo real entram no marco 5 |
| 2026-09-29 | Modos `auto` ("Automático") e `dontAsk` ("Só o pré-aprovado") aceitos sem confirmação; só `bypassPermissions` pede confirmação |
| 2026-09-29 | Sessões do app herdam o modo padrão do CLI do usuário |
| 2026-09-29 | "Permitir" e "Negar" nos cartões de "Todas as sessões" entram no marco 6 |
| 2026-09-29 | MVP (marcos 0 a 6) concluído, revisado e testado contra o SDK real |
| 2026-09-29 | "Agora" do Dashboard limitado a 6 cartões com link para a Inbox; Recentes só com conversas abertas, guardadas no navegador |
| 2026-09-29 | Nova navegação no estilo do Paperclip vira o marco 7 e substitui as colunas lado a lado. Agrupador passa a marco 8 e progresso de planos a marco 9 |
| 2026-09-29 | Pendências do marco 7 fechadas, revisadas e marco 7 concluído de novo |
| 2026-09-29 | Progresso de planos lido do arquivo do plano, com regra de marcação no CLAUDE.md global; ferramenta de tarefas descartada por não existir nas sessões com Opus |
| 2026-09-29 | Marco 9 concluído: progresso lido do plano, vínculo automático, sinal de turno aberto das conversas do CLI; revisado e testado no app real |
| 2026-09-30 | Marco 10 concluído: agente de resumos com leitura incremental, fases congeladas, selo de plano concluído no app e aba nas Preferências; revisado e testado contra o SDK real |
| 2026-09-30 | Agente de resumos vira o marco 10: uma chamada curta do SDK por sessão, incremental, sem ferramentas, configurável numa aba das Preferências |
| 2026-09-28 | Commits por tarefa autorizados neste projeto, no formato de mensagem do usuário. Push só a pedido |
| 2026-09-30 | Marco 12 concluído: conversa do CLI no meio de um turno conta como "Em execução"; sessões de worktree são indexadas sob o projeto dono e retomadas na worktree só quando a transcrição está na pasta dela; o marco foi numerado 11 porque o main já tem um marco 10 |
| 2026-09-30 | Recentes do menu lateral passa a listar todas as conversas não finalizadas, pela última interação, e deixa de ser guardado no navegador. Substitui a decisão de 2026-09-29 e a ordem estável do marco 12 |
| 2026-09-30 | Comandos (`/`) e menções (`@`) no campo de mensagem viram o marco 13, seguindo o comportamento da extensão do VSCode |
| 2026-09-30 | Marco 12 concluído de novo, depois de reaberto: subagentes em segundo plano do app e do CLI contam como "Em execução" (no CLI, cada arquivo de subagente vale até o próprio `end_turn` ou 20 min sem escrever), Recentes por última interação e nome do projeto no menu lateral; revisado pelo `milestone-reviewer` |
