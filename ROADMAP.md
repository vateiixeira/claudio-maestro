# Roadmap do Vini7 Vibing

Acompanha a construção completa do app. É a fonte única do que está feito e do que falta.

Última atualização: 2026-09-28

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
| 1. Conversa funcionando | Um projeto, uma sessão com streaming e permissões | Em andamento | 9 de 13 |
| 2. Multissessão | Colunas, estados e menu lateral | Não iniciado | 0 de 10 |
| 3. Histórico | Retomada, busca e ocultação | Não iniciado | 0 de 7 |
| 4. Git | Branches em todas as telas e painel de alterações | Não iniciado | 0 de 8 |
| 5. Controles | Modelo, raciocínio, modo, imagens, voz, subagentes, perguntas e planos | Não iniciado | 0 de 13 |
| 6. Acabamento | Erros, robustez e uso diário | Não iniciado | 0 de 9 |
| 7. Agrupador de sessões | Organizar sessões relacionadas dentro do projeto | Depois do MVP | 0 de 9 |
| 8. Progresso de planos | Etapa atual de cada plano em execução, fixa na tela | Depois do MVP | 0 de 7 |

Os marcos 0 a 6 formam o MVP. Os marcos 7 e 8 só começam com o MVP completo e funcionando.

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

- [ ] Estrutura com Vite, Tailwind e as cores e fontes da identidade visual
- [ ] Menu lateral com projetos e tela de novo projeto
- [ ] Coluna de sessão: conversa com streaming, blocos de texto, raciocínio, leitura, edição e comando
- [ ] Cartão de permissão e campo de mensagem com Enter e Ctrl+Enter

## Marco 2. Multissessão

Objetivo: acompanhar várias sessões de projetos diferentes ao mesmo tempo.

- [ ] Várias sessões ativas no backend, cada uma com seu processo
- [ ] Desligamento de sessão ociosa após 30 minutos, com religamento automático
- [ ] Colunas lado a lado, largura ajustável, rolagem horizontal
- [ ] Layout salvo e restaurado ao reabrir o app
- [ ] Três estados exibidos: em execução, aguardando você, finalizada
- [ ] Marcar sessão como finalizada e reabrir
- [ ] Renomear sessão pela interface, gravando com `rename_session` do SDK para o nome valer também no CLI
- [ ] Menu lateral com sessões abertas por projeto e contadores
- [ ] Tela do projeto com sessões nos três blocos
- [ ] Tela "Todas as sessões" com filtro por projeto

## Marco 3. Histórico

Objetivo: continuar no app o trabalho que começou no CLI ou na extensão.

- [ ] Índice de sessões sincronizado a partir do histórico
- [ ] Sessões de repositórios dentro da pasta do projeto entram no projeto
- [ ] Abrir sessão antiga carrega a conversa sem criar processo
- [ ] Retomar sessão antiga ao enviar mensagem
- [ ] Busca no menu lateral por título, resumo e primeiro prompt
- [ ] Sessões sem atividade há mais de 3 dias ocultas do menu, com contagem
- [ ] Aviso ao retomar sessão modificada no último minuto por outro processo

## Marco 4. Git

Objetivo: saber em que branch cada repositório está e ver o que o Claude alterou.

- [ ] Descoberta de repositórios na pasta do projeto, até 3 níveis
- [ ] Leitura de branch, inclusive com HEAD solto
- [ ] Branches no menu lateral, no cabeçalho da sessão, na tela do projeto e no novo projeto
- [ ] Atualização automática: ao fim de cada turno e a cada 30 segundos
- [ ] Painel de alterações fechado por padrão, aberto ao clicar em uma edição
- [ ] Diff da edição clicada e lista de arquivos modificados por repositório
- [ ] Diff atual de um arquivo contra o último commit
- [ ] "Abrir no editor" com comando configurável

## Marco 5. Controles

Objetivo: tudo o que o CLI permite ajustar em uma sessão, pela interface.

- [ ] Lista de modelos vinda do SDK
- [ ] Troca de modelo com a sessão ativa
- [ ] Troca de modo de permissão, com confirmação para "Sem perguntas"
- [ ] Troca de raciocínio por reconexão entre turnos
- [ ] Campo de mensagem que cresce até 40% da coluna
- [ ] Colar e arrastar imagens, com miniatura e remoção
- [ ] Perguntas do Claude respondidas pela interface
- [ ] Aprovação de plano pela interface
- [ ] Blocos de busca e lista de tarefas
- [ ] Subagentes visíveis na sessão: um cartão por subagente com tipo, descrição e estado (rodando, concluído, com erro), e as ações dele (ferramentas, edições, comandos) aparecendo em tempo real dentro do cartão. Vale também para subagentes em segundo plano
- [ ] Cartão genérico para ferramentas e MCPs sem bloco próprio
- [ ] Saídas longas truncadas em 200 linhas
- [ ] Ditado por voz: botão de microfone no campo de mensagem que transcreve a fala em texto, para revisar antes de enviar (tecnologia a definir, ver "Pontos em aberto")

## Marco 6. Acabamento

Objetivo: o app aguenta o uso diário sem surpresas.

- [ ] Mensagem enviada durante um turno ou com permissão pendente não se perde
- [ ] Recarregar a página no meio de uma resposta preserva texto e permissão pendente
- [ ] Duas abas abertas ficam consistentes; resposta duplicada é recusada sem erro
- [ ] Processo do Claude morto, CLI ausente e login expirado mostram erro legível
- [ ] Limite da assinatura atingido mostra o horário de liberação
- [ ] Projeto com pasta apagada aparece como indisponível
- [ ] Caminhos com espaços, acentos e links simbólicos para fora da pasta pessoal
- [ ] Revisão de acessibilidade: teclado, contraste e foco
- [ ] Fontes servidas pelo próprio app; hoje vêm do Google Fonts e dependem de internet

## Marco 7. Agrupador de sessões

Objetivo: juntar sessões relacionadas dentro de um projeto, para enxergar o trabalho como um conjunto.

Caso de uso que motivou: uma sessão gera um prompt, e esse prompt é executado em uma sessão nova. As duas pertencem ao mesmo trabalho, mas hoje apareceriam soltas na lista.

Pedido pelo usuário em 2026-09-28. Só começa depois do MVP completo e funcionando.

O agrupador existe só no banco do backend. O Claude e o CLI não sabem dele, e o histórico em `~/.claude/projects` não muda.

- [ ] Tabela de agrupadores no SQLite, ligada ao projeto, e vínculo da sessão com o agrupador
- [ ] Criar agrupador dentro de um projeto
- [ ] Renomear agrupador
- [ ] Remover agrupador; as sessões dele voltam a ficar soltas e não são apagadas
- [ ] Mover sessão para um agrupador, trocar de agrupador e tirar do agrupador
- [ ] Criar sessão nova já dentro do agrupador de uma sessão aberta
- [ ] Menu lateral mostra as sessões dentro dos agrupadores, que podem ser recolhidos
- [ ] Tela do projeto mostra os agrupadores
- [ ] Busca de sessões também encontra pelo nome do agrupador

A definir quando o marco for desenhado:

| Pergunta | Por que importa |
|---|---|
| Uma sessão pode estar em mais de um agrupador? | Muda o modelo de dados. O mais simples é um só |
| Como os agrupadores aparecem em "Todas as sessões"? | Essa tela organiza por estado; agrupador seria um segundo eixo |
| Agrupador com todas as sessões finalizadas some do menu? | Segue ou não a regra de ocultação das sessões |
| O agrupador tem cor ou só nome? | O projeto já tem cor; duas cores podem confundir |

## Marco 8. Progresso de planos

Objetivo: saber, sem perguntar ao Claude, em que etapa está cada sessão que executa um plano.

Caso de uso que motivou: um plano de implementação com 15 tarefas roda por muito tempo, e o Claude não diz em qual tarefa está, embora controle isso internamente.

Pedido pelo usuário em 2026-09-28. Só começa depois do MVP completo e funcionando.

Fonte dos dados: o Claude registra o progresso pela ferramenta de lista de tarefas. Cada chamada traz a lista inteira com o estado de cada item (pendente, em andamento, concluído) e passa pelo app como qualquer outra ferramenta. Os planos do fluxo de brainstorming também ficam em arquivos `docs/superpowers/plans/*.md`, com caixas de marcação.

- [ ] Guardar na sessão a lista de tarefas mais recente, a partir das chamadas da ferramenta de lista de tarefas
- [ ] Barra fixa no topo da coluna da sessão: tarefa atual, posição ("7 de 15") e barra de progresso
- [ ] Barra expansível para a lista completa, com o estado de cada tarefa
- [ ] Indicação de plano em execução e etapa atual no menu lateral, ao lado da sessão
- [ ] Tela do projeto destaca as sessões que executam um plano, com a etapa de cada uma
- [ ] Ligar a sessão ao arquivo do plano em `docs/superpowers/plans/` quando ela o leu ou editou, com link para abrir
- [ ] Lista de tarefas recuperada ao retomar uma sessão do histórico

A definir quando o marco for desenhado:

| Pergunta | Por que importa |
|---|---|
| Qual versão da ferramenta de lista de tarefas o Claude usa hoje? | Existe a ferramenta única que reenvia a lista inteira e uma família de ferramentas que cria e atualiza tarefas uma a uma. O formato dos dados muda |
| Subagentes que executam tarefas do plano entram no progresso? | No fluxo com subagentes, quem executa é outro agente, mas quem atualiza a lista é a sessão principal |
| O que mostrar quando a lista é abandonada no meio? | Uma lista velha fixa na tela engana mais do que ajuda |

## Fora do MVP

Ideias registradas para depois. Não entram sem decisão do usuário.

- Terminal embutido
- Editor de código e árvore de arquivos
- Tema claro
- Busca no texto das mensagens
- Commit, push e troca de branch pela interface
- Indicador de consumo dos limites da assinatura
- Agrupar projetos no menu (diferente do agrupador de sessões, que é o marco 7)
- Execução em Docker
- Manter o app sempre ativo, iniciando junto com a máquina

## Pontos em aberto

| Ponto | Situação |
|---|---|
| Docker | Adiado. Exigiria rodar o Claude dentro do container, com as pastas montadas no mesmo caminho do host. Não testado |
| Mesma sessão aberta no app e no CLI ao mesmo tempo | Risco de embaralhar o histórico. O app só avisa |
| O que o SDK entrega sobre subagentes | Verificar antes do marco 5. Candidatos: mensagens com `parent_tool_use_id`, a opção `forward_subagent_text`, as mensagens `TaskStartedMessage`, `TaskProgressMessage` e `TaskNotificationMessage`, e as funções `list_subagents` e `get_subagent_messages`. A conversão de mensagens já guarda `parent_tool_use_id` em cada item |
| Tecnologia do ditado por voz | Decidir antes do marco 5. Opção A: reconhecimento de fala do navegador, sem dependência e leve, mas só no Chrome e no Edge, precisa de internet e envia o áudio ao Google. Opção B: Whisper rodando no backend, privado e offline, mas baixa um modelo de centenas de MB e usa CPU a cada ditado. Recomendação inicial: A |
| Variáveis `CLAUDE*` herdadas ao iniciar o SDK | O teste passou removendo-as. Não se sabe se falha com elas |

## Decisões

| Data | Decisão |
|---|---|
| 2026-09-28 | Backend em Python com FastAPI; frontend em Vue 3 |
| 2026-09-28 | Um `ClaudeSDKClient` por sessão ativa, dentro do backend |
| 2026-09-28 | Login de assinatura existente, sem API key |
| 2026-09-28 | Projeto é uma pasta, que pode conter vários repositórios |
| 2026-09-28 | SQLite só para metadados; conversas ficam em `~/.claude/projects` |
| 2026-09-28 | Sem login nem senha; acesso só por localhost |
| 2026-09-28 | Layout em colunas; painel de alterações abre só ao clicar em uma edição |
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
| 2026-09-28 | Commits por tarefa autorizados neste projeto, no formato de mensagem do usuário. Push só a pedido |
