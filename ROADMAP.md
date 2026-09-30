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
| 8. Agrupador de sessões | Organizar sessões relacionadas dentro do projeto | Em andamento | 0 de 10 |
| 9. Progresso de planos | Etapa atual de cada plano em execução, fixa na tela | Concluído | 11 de 11 |
| 10. Ajustes de sessões e menu lateral | Em execução no menu, worktree da sessão, Detalhes ajustável e ditado no modal | Em andamento | 1 de 12 |

Os marcos 0 a 6 formam o MVP, concluído em 2026-09-29. O marco 7 foi pedido pelo usuário em 2026-09-29. O marco 9 foi concluído em 2026-09-29 e o marco 8 começou em 2026-09-30, ambos a pedido do usuário. O marco 10 começou em 2026-09-30, a pedido do usuário, em paralelo ao marco 8.

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

- [ ] Tabela de agrupadores no SQLite, ligada ao projeto, e vínculo da sessão com o agrupador
- [ ] Criar agrupador dentro de um projeto
- [ ] Renomear agrupador
- [ ] Remover agrupador; as sessões dele voltam a ficar soltas e não são apagadas
- [ ] Mover sessão para um agrupador, trocar de agrupador e tirar do agrupador (propriedade em Detalhes)
- [ ] Criar sessão nova já dentro do agrupador de uma sessão aberta
- [ ] Menu lateral: cada projeto vira uma árvore recolhível com seus agrupadores e as sessões ativas deles
- [ ] Tela do projeto mostra os agrupadores em cima e as sessões sem agrupador embaixo
- [ ] Etiqueta do agrupador na linha de conversa e filtro por agrupador na tela Conversas
- [ ] Busca de sessões também encontra pelo nome do agrupador

Decidido no desenho (2026-09-30): uma sessão fica em no máximo um agrupador; o agrupador tem só nome, sem cor; o menu mostra só os agrupadores, com as sessões ativas, e o agrupador sem sessão ativa fica numa linha apagada; a tela Conversas continua por data, com etiqueta e filtro.

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

## Marco 10. Ajustes de sessões e menu lateral

Objetivo: enxergar o que roda (inclusive no terminal) e onde cada sessão trabalha, com ajustes de uso diário no menu lateral, no Detalhes e no modal.

Pedido pelo usuário em 2026-09-30. Feito na worktree `.claude/worktrees/melhorias-ui-sessoes`, em paralelo ao marco 8.

- Spec: `docs/superpowers/specs/2026-09-30-ajustes-sessoes-menu-lateral-design.md`
- Plano: `docs/superpowers/plans/2026-09-30-ajustes-sessoes-menu-lateral.md`

- [x] Detectar a worktree atual pela transcrição (`worktree.py`) (2026-09-30)
- [ ] Colunas de worktree, branch e pasta do histórico na sessão
- [ ] Conversa do CLI no meio de um turno aparece como "Em execução"
- [ ] Indexar sessões guardadas nas pastas das worktrees
- [ ] Ler o histórico pela pasta certa e retomar a sessão na worktree
- [ ] Worktree e branch no cabeçalho, no Detalhes e na lista
- [ ] Renomear só pelo clique no título
- [ ] Largura ajustável do painel Detalhes
- [ ] Progresso do plano no painel Detalhes
- [ ] Menu lateral com "Em execução", sigla do projeto e Recentes em ordem estável
- [ ] Ditado no modal de nova conversa
- [ ] Retomada de sessão movida para worktree conferida contra o SDK real

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

## Pontos em aberto

| Ponto | Situação |
|---|---|
| Docker | Adiado. Exigiria rodar o Claude dentro do container, com as pastas montadas no mesmo caminho do host. Não testado |
| Mesma sessão aberta no app e no CLI ao mesmo tempo | Risco de embaralhar o histórico. O app só avisa |
| O que o SDK entrega sobre subagentes | Verificado em 2026-09-29; ver "Fatos verificados para o marco 5" no prompt de construção |
| Usar o Vibing no próprio repositório | O backend roda com recarga automática em `backend/`. Uma edição do Claude nessa pasta reinicia o backend e derruba todas as sessões. Evitar ou rodar sem `--reload` nesse caso |
| Tecnologia do ditado por voz | Decidido em 2026-09-29: reconhecimento do navegador (Chrome/Edge). O áudio vai ao serviço de reconhecimento do navegador |
| Variáveis `CLAUDE*` herdadas ao iniciar o SDK | O teste passou removendo-as. Não se sabe se falha com elas |
| Conversa do CLI ativa aparece como "Aguardando você" | Uma conversa conduzida pelo CLI não tem cliente no app, então o estado exibido é "Aguardando você" mesmo com o CLI trabalhando. O marco 9 criou o sinal `cli_running` e o usa só no progresso do plano. Decidir se ele também muda o estado exibido e as contagens da Inbox e do Dashboard |
| Contagem de turnos em casos raros | Se o CLI juntar duas mensagens num turno só, ou mandar um `init` por outro motivo logo depois de um turno autônomo, a conversa fica em "rodando" até o próximo turno. Nunca observado |

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
| 2026-09-28 | Commits por tarefa autorizados neste projeto, no formato de mensagem do usuário. Push só a pedido |
