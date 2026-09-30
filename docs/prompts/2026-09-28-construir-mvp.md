# Construir o Vini7 Vibing

Você vai construir o Vini7 Vibing neste repositório (`/home/vi/dev/vini7-vibing`), que hoje só tem `CLAUDE.md`, `ROADMAP.md`, a pasta `docs/` e um git inicializado sem commits.

## O que é e para quem

Um app web local que substitui a extensão do VSCode e o CLI do Claude Code no meu uso diário. Roda na minha máquina Linux, abre no navegador e controla sessões do Claude Code pelo Claude Agent SDK em Python. Sou o único usuário.

Os dois problemas que ele resolve: a extensão do VSCode é pesada e ruim para trabalhar em vários projetos ao mesmo tempo, e o terminal dificulta ler diffs, saídas e estados. Na dúvida entre duas soluções, prefira a que mantém o app leve e a leitura clara. Não transforme o app em um IDE.

## O que já está decidido

Requisitos e design visual já foram discutidos e aprovados por mim. Não refaça brainstorming, não peça aprovação de design e não escreva spec. Planeje como achar melhor e implemente.

Referências no repositório e fora dele:

- `CLAUDE.md`: regras do projeto, portas e forma de execução. Vale sobre este prompt se houver divergência.
- `ROADMAP.md`: os marcos e os itens de cada um. Siga a ordem dele e mantenha-o atualizado conforme avança.
- `docs/superpowers/specs/2026-09-28-vini7-vibing-design.md`: detalhamento de modelo de dados, estados, rotas, segurança e erros. Use como referência. Onde ela divergir deste prompt, este prompt vale.
- Design visual aprovado: https://claude.ai/artifact/JAVD4f5uhJMr5WZodBe97A (leia com a ferramenta de artefatos, não com busca web). Seis telas: sessões em colunas, painel de alterações aberto, tela do projeto, todas as sessões, novo projeto e o menu lateral.

## Stack

- Monolito: `backend/` e `frontend/` no mesmo repositório, `pyproject.toml` na raiz.
- Backend: Python 3.13, FastAPI, uv, SQLite, `claude-agent-sdk` 0.2.161 ou superior, pytest.
- Frontend: Vue 3, Vite, TypeScript, Pinia, Vue Router, Tailwind CSS, Vitest, pnpm.
- Roda direto na máquina, sem Docker, em modo de desenvolvimento com recarga automática. Backend em `127.0.0.1:6660`, frontend em `127.0.0.1:6600` com proxy de `/api` e `/ws` para o backend. Eu acesso o app em `http://localhost:6600`.

## Requisitos

Projetos

- Um projeto é uma pasta, com nome e cor. A pasta pode conter vários repositórios git em subpastas; a sessão roda na pasta do projeto e trabalha em todos.
- Criar projeto por um navegador de pastas servido pelo backend, limitado à minha pasta pessoal.
- Mostrar a branch git de cada repositório do projeto no menu lateral, no cabeçalho da sessão, na tela do projeto e na criação do projeto. Isso é muito importante para mim. Projeto sem git mostra "sem repositório git".

Sessões

- Conversa com streaming e renderização própria por tipo de bloco: texto em markdown, raciocínio recolhido, leitura, edição com diff, comando com saída, busca, subagente, e um cartão genérico para o resto.
- Várias sessões abertas lado a lado em colunas de largura ajustável, inclusive de projetos diferentes.
- Três estados: em execução, aguardando você, finalizada. Uma sessão ociosa ou com erro conta como aguardando. Finalizada é a que eu marquei, ou a que está sem atividade há mais de 3 dias (valor configurável).
- Tela "Todas as sessões" com os três estados juntando todos os projetos.
- Retomar sessões antigas, inclusive as criadas pelo CLI ou pela extensão. O projeto também mostra sessões cuja pasta é um repositório dentro dele.
- Permissões respondidas pela interface: permitir uma vez, permitir sempre, negar. Perguntas do Claude e aprovação de planos seguem o mesmo caminho.
- Trocar modelo, nível de raciocínio e modo de permissão por sessão, no rodapé da coluna.
- Renomear a sessão pela interface. Grave com `rename_session` do SDK, para o nome valer também no CLI.

Menu lateral

- Marca "Vini7 Vibing".
- Busca de sessões, que também encontra as antigas e ocultas. Procura em título, resumo e primeiro prompt.
- Por projeto: branches e sessões abertas com seu estado. Sessões finalizadas não aparecem; mostra só a contagem das ocultas.

Campo de mensagem

- Cresce conforme o texto, até 40% da altura da coluna.
- Enter envia. Ctrl+Enter e Shift+Enter quebram linha.
- Ctrl+V cola imagens (PNG, JPEG, GIF, WebP; até 5 MB cada, 10 por mensagem).

Painel de alterações

- Fechado por padrão. Só abre quando clico em uma edição na conversa.
- Mostra o diff daquela edição e os arquivos modificados na sessão, agrupados por repositório com a branch.
- Botão "Abrir no editor" com comando configurável.

Dados e acesso

- SQLite só para metadados: projetos, índice de sessões, layout e preferências. As conversas ficam em `~/.claude/projects` e continuam compatíveis com o CLI. Não copie conversas para o banco.
- Sem login e sem senha.
- Use o login de assinatura que já existe na máquina. Não configure nem peça `ANTHROPIC_API_KEY`.
- Carregue as configurações do Claude como o CLI faz (CLAUDE.md, skills, hooks, plugins, MCPs): deixe `setting_sources` no padrão nas sessões reais.

Fora do escopo: terminal embutido, editor de código, árvore de arquivos, tema claro, acesso por rede, busca no texto das mensagens, commit ou troca de branch pela interface.

## Identidade visual

Sempre em modo escuro, no estilo neutro de paperclip.ing: preto, bordas de 1 px, cantos de 8 px, rótulos em fonte monoespaçada, pouca cor.

- Fundo #0A0A0A, painel #111111, cartão #171717, elevado #1A1A1A.
- Borda #262626, borda forte #333333.
- Texto #FAFAFA, texto secundário #A1A1A1.
- Verde, primária: #4ADE80 com texto #052E14 sobre ela; tom claro #86EFAC. Marca, ações principais e o que está rodando.
- Laranja, secundária: #FB923C com texto #2A1200 sobre ela; tom claro #FDBA74. Tudo o que espera por mim.
- Diff adicionado: fundo #0F2A1A, texto #86EFAC. Diff removido: fundo #2D1215, texto #FCA5A5.
- Fontes: Geist na interface, JetBrains Mono em código, caminhos e branches.
- Cada estado tem forma própria além da cor: círculo para rodando, triângulo para aguardando, visto para finalizada.
- Não use a marca "Claude Code" na interface.

## Segurança

O app executa comandos na minha máquina, então qualquer site aberto no navegador é uma ameaça a um servidor local.

- Escute só em 127.0.0.1.
- Recuse requisições cujo cabeçalho Host não seja localhost ou 127.0.0.1 nas portas 6600 e 6660.
- Recuse WebSockets e requisições que alteram estado cuja origem não seja a do próprio app.
- Não libere CORS.
- Todo caminho recebido precisa ser resolvido e estar dentro da pasta de um projeto registrado. Links simbólicos que apontam para fora contam como fora.
- Execute git e o editor com argumentos em lista, sem shell.

## Fatos verificados sobre o SDK

Testei estes pontos nesta máquina em 2026-09-28, com `claude-agent-sdk` 0.2.161 e Claude Code 2.1.284. Parta deles em vez de redescobrir.

Autenticação

- O SDK funciona com a minha assinatura, sem API key. A mensagem de sistema inicial veio com `apiKeySource` igual a `none`.

Cliente

- Use `ClaudeSDKClient`, que sempre opera em modo streaming. Métodos úteis: `connect`, `query`, `receive_messages`, `receive_response`, `interrupt`, `set_model`, `set_permission_mode`, `get_server_info`, `get_context_usage`, `rewind_files`, `disconnect`.
- Não existe troca de raciocínio ao vivo. O campo `effort` só vale ao conectar. Para trocar, reconecte com `resume` entre um turno e outro.
- `ClaudeAgentOptions.session_id` aceita um UUID nosso para uma sessão nova, e o SDK usa exatamente esse id. Para sessão existente, use `resume`. Antes da primeira mensagem, `get_session_info` devolve `None`; isso serve para distinguir os dois casos.
- `get_server_info()["models"]` lista os modelos com `value`, `displayName`, `description`, `supportsEffort` e `supportedEffortLevels`. Use isso para os seletores.
- `receive_response` termina no primeiro resultado. Para aceitar mensagens enviadas durante um turno, leia com `receive_messages` em uma tarefa permanente por sessão.

Fluxo de mensagens em um turno, com `include_partial_messages=True`

- `SystemMessage` com subtipo `init` (traz `session_id`, `model`, `permissionMode`), depois `status` e, durante o raciocínio, `thinking_tokens`.
- `StreamEvent` com `message_start` (traz o id da mensagem), `content_block_start` (traz `index` e o tipo do bloco), e deltas `text_delta`, `thinking_delta`, `input_json_delta` e `signature_delta`.
- O SDK emite um `AssistantMessage` por bloco de conteúdo, não por resposta. Todos os blocos da mesma resposta compartilham o `message_id`, e cada `AssistantMessage` chega antes do `content_block_stop` do seu bloco. Identifique cada bloco por id da mensagem mais índice.
- O resultado de ferramenta chega como `UserMessage` com `ToolResultBlock`. O campo `tool_use_result` traz dados estruturados; para Write e Edit inclui `structuredPatch`, `filePath` e `originalFile`. Use isso no painel de alterações.
- `ResultMessage` encerra o turno, com custo, duração e uso.
- `RateLimitEvent` informa o estado dos limites da assinatura.

Permissões

- `can_use_tool(tool_name, input, context)` recebe em `context`: `display_name`, `description`, `title`, `tool_use_id` e `suggestions`. No teste com Write, a sugestão foi trocar o modo da sessão para `acceptEdits`.
- Responda com `PermissionResultAllow(updated_input, updated_permissions)` ou `PermissionResultDeny(message, interrupt)`. "Permitir sempre" é devolver as sugestões recebidas em `updated_permissions`.
- O callback pode ficar pendente pelo tempo que for preciso.
- Ferramentas já liberadas pelas minhas configurações não passam pelo callback.

Turnos e interrupção (verificado em 2026-09-28)

- Uma mensagem enviada com `query` durante um turno em andamento é respondida depois dele, em um turno próprio. Cada envio produz exatamente um `ResultMessage`.
- `interrupt()` com permissão pendente cancela a tarefa do `can_use_tool`, que recebe `CancelledError`. A ferramenta não executa. Chegam um `UserMessage` com `ToolResultBlock` de recusa, um `UserMessage` com `TextBlock` "[Request interrupted by user for tool use]" e um `ResultMessage` com `subtype="error_during_execution"`, `is_error=True` e `terminal_reason="aborted_tools"`.
- Depois da interrupção, a mesma sessão aceita novas mensagens normalmente.
- Interromper um turno com outra mensagem já na fila preserva a fila: o turno interrompido termina com `error_during_execution` e `terminal_reason="aborted_streaming"`, e a mensagem seguinte é respondida em seguida, com seu próprio `ResultMessage`.
- Uma sessão interrompida no `message_start`, antes de qualquer texto, já existe em disco: aparece em `list_sessions` e `get_session_messages` devolve a mensagem do usuário.
- Conectar com `session_id` de uma sessão que já existe, sem `resume`, faz o processo sair com erro: "Session ID ... is already in use", que chega como `ProcessError`. Com `resume` igual ao mesmo id, funciona. Por isso a checagem de histórico precisa ser confiável.

Histórico

- `list_sessions(directory, limit, offset)` devolve `session_id`, `summary`, `custom_title`, `first_prompt`, `git_branch`, `cwd`, `created_at` e `last_modified`. Listar 40 pastas levou 0,15 s.
- `get_session_messages(session_id, directory)` devolve entradas `user` e `assistant`. O campo `message` é um dicionário no formato da API, e cada entrada de assistente traz um bloco, como no fluxo ao vivo.
- Também existem `rename_session`, `tag_session`, `delete_session` e `fork_session`.

Cuidados ao testar contra o SDK real

- Cada chamada consome a minha assinatura. Faça poucas, com prompts mínimos e o modelo `haiku`.
- Rode em uma pasta temporária com `setting_sources=[]`, para não disparar meus hooks e plugins.
- Apague as sessões de teste com `delete_session` ao terminar, para não sujar meu histórico.
- Se você estiver rodando dentro de uma sessão do Claude Code, o processo herda variáveis como `CLAUDECODE` e `CLAUDE_CODE_SESSION_ID`. Meu teste passou removendo do ambiente todas as variáveis que começam com `CLAUDE`. Não testei sem remover.
- Os testes automatizados não devem tocar o SDK real. Isole o SDK atrás de uma interface e use um cliente falso que emite mensagens roteirizadas.

Versões disponíveis hoje: FastAPI 0.141, uvicorn 0.54, pytest 9.1, Vue 3.5, Vite 8.3, Pinia 4, Vue Router 5.3, Tailwind 4.3, TypeScript 7, Vitest 5.

## Ordem de trabalho

Cada marco deve terminar com algo que eu consiga usar. Conclua um antes de começar o seguinte. Os itens de cada marco estão no `ROADMAP.md`.

0. Fundação: estrutura do repositório, backend e frontend no ar com recarga automática, testes rodando.
1. Conversa funcionando: segurança, projetos, uma sessão com streaming, blocos básicos, permissões.
2. Multissessão: colunas, estados, menu lateral com sessões, "Todas as sessões", tela do projeto.
3. Histórico: índice de sessões, retomada, busca, ocultação por inatividade.
4. Git: descoberta de repositórios, branches em todas as telas, painel de alterações, abrir no editor.
5. Controles: modelo, raciocínio, modo, imagens, perguntas e planos, blocos restantes.
6. Acabamento: erros, robustez e as situações da seção seguinte.

O marco 7 do roadmap, o agrupador de sessões, fica para depois do MVP. Não o implemente agora. Só evite decisões no modelo de dados que dificultem ligar uma sessão a um agrupador mais tarde.

## Situações que o app precisa aguentar

Escreva testes para estas, porque são as que mais devem aparecer no uso real:

- Mensagem enviada enquanto um turno roda ou enquanto há uma permissão pendente: é aceita e não se perde.
- Página recarregada no meio de uma resposta: o texto já recebido e a permissão pendente reaparecem, e responder ainda funciona.
- Permissão respondida duas vezes, ou respondida em uma aba com outra aba aberta: a segunda resposta é recusada sem erro, e as duas abas ficam consistentes.
- Processo do Claude morre no meio do turno, CLI ausente ou login expirado: a sessão mostra um erro legível e reenviar reconecta.
- Pasta do projeto apagada ou renomeada depois de criada: o projeto aparece como indisponível e o resto do app segue funcionando.
- Saída de ferramenta muito longa: truncada em 200 linhas, sem travar a interface.
- Caminhos com espaços e acentos, e link simbólico dentro da pasta pessoal apontando para fora dela.

## Regras de trabalho

- Commits por tarefa estão autorizados neste projeto, no formato descrito no `CLAUDE.md`. Faça um ao concluir cada item do roadmap, depois de ver os testes passarem. Não faça push.
- Atualize o `ROADMAP.md` a cada item concluído, com a data. Só marque um item depois de ver os testes dele passarem.
- Escreva os testes antes do código que eles cobrem.
- Textos da interface e documentação em português brasileiro. Código e identificadores em inglês.
- Não sei dizer se o mesmo histórico aberto no app e no CLI ao mesmo tempo se corrompe. Não tente resolver isso; só avise na interface quando a sessão retomada tiver sido modificada no último minuto.

## Como encerrar

Ao fim de cada marco, rode os testes do backend e do frontend e a compilação do frontend, atualize o `ROADMAP.md` e me diga o que passou e o que falhou, com a saída dos comandos. Ao fim do marco 1 e do marco 5, faça também um teste real contra o SDK seguindo os cuidados acima.

No relatório final, separe o que você verificou rodando do que só escreveu sem conseguir testar, e liste o que ficou pendente.

## Fatos verificados para o marco 5 (2026-09-29, SDK 0.2.161, modelo haiku)

Subagentes
- Todo `Agent` roda em segundo plano: o resultado da ferramenta volta na hora ("Async agent launched successfully") e o `ResultMessage` do turno pode chegar antes de o subagente terminar.
- As mensagens do subagente chegam em tempo real como `AssistantMessage`/`UserMessage` com `parent_tool_use_id` igual ao id do `tool_use` do Agent. Não há `StreamEvent` (deltas) do subagente. Com `forward_subagent_text=True` chegam também os `TextBlock`s dele.
- Mensagens de sistema: `SystemMessage` `background_tasks_changed` (campo `tasks`); `TaskStartedMessage` (`task_id`, `tool_use_id`, `description`, `task_type`, e em `data` `subagent_type`, `is_backgrounded`, `prompt`); `TaskProgressMessage` a cada ferramenta (`description`, `usage{total_tokens, tool_uses, duration_ms}`, `last_tool_name`); `TaskUpdatedMessage` (`patch`, `status`); `TaskNotificationMessage` (`status`, `summary`, `output_file`, `tool_use_id`, `usage`).
- Quando um subagente em segundo plano termina depois do fim do turno, o CLI emite um novo `init` e **abre um turno sozinho**, sem prompt do usuário, terminando com outro `ResultMessage`. A contagem de turnos pendentes não pode assumir um `ResultMessage` por envio nesse caso.
- `list_subagents` e `get_subagent_messages` só enxergam o subagente depois do fim do turno.

AskUserQuestion
- Só existe com `can_use_tool`. `input`: `{"questions":[{"question","header","options":[{"label","description"}],"multiSelect"}]}`.
- Resposta: `PermissionResultAllow(updated_input={**input, "answers": {"<texto da pergunta>": "<label escolhido>"}})`. A resposta chega ao modelo. Múltipla escolha não testada.

Plano
- `ExitPlanMode` passa por `can_use_tool` com `input={"plan": "<markdown>", "planFilePath": "~/.claude/plans/<slug>.md"}`. O arquivo do plano é gravado antes, fora da pasta do projeto, sem pedir permissão.
- Negar com mensagem: o modelo reescreve o plano e chama `ExitPlanMode` de novo. Permitir: o modelo executa no mesmo turno e o modo passa sozinho de `plan` para `default` (aparece no próximo `init`).

Troca ao vivo
- `set_model` e `set_permission_mode` entre turnos aparecem no `init` seguinte. O turno seguinte começa com um `UserMessage` de conteúdo string `<local-command-stdout>Set model to ...</local-command-stdout>`, que não é fala do usuário.

Lista de tarefas
- Não existe `TodoWrite`. Com haiku: `TaskCreate {"subject","description"}` ("Task #1 created successfully"), `TaskUpdate {"taskId","status"}`, `TaskList`, `TaskGet`, `TaskStop`, como ferramentas diferidas (o modelo chama `ToolSearch` antes). Com sonnet 5.5 essas ferramentas não estavam disponíveis. O app não pode supor que existam.

Outros
- Mesmo com `setting_sources=[]`, a sessão carregou os conectores MCP do claude.ai da conta.

## Fatos verificados no teste real do marco 5 (2026-09-29)

- Com `setting_sources` padrão e `defaultMode: "auto"` no `~/.claude/settings.json`, uma sessão aberta pelo SDK reporta `permissionMode: "default"` no `init`. O modo `auto` do CLI não é herdado pelo SDK.
- `background_tasks_changed.tasks` é uma lista de `{task_id, task_type, description}`. Fica vazia quando a última tarefa termina, no mesmo instante de `task_updated` e `task_notification`.
- A `description` do `task_progress` vem em inglês e resume a ação atual ("Reading dados.txt").
- Itens do subagente e atualizações do cartão chegam com a sessão em `idle`, entre o fim do turno e o turno autônomo. O `init` do turno autônomo chega antes de o estado passar a `running`.
- `get_server_info()["models"]` trouxe 12 modelos com `displayName` em inglês; o haiku vem com `supportedEffortLevels=None`, mas aceita `effort`.

## Fatos verificados no teste real do marco 6 (2026-09-29)

- Cliente com `setting_sources=[]`, sem enviar mensagem: `connect` + `get_server_info()` trouxe os 12 modelos em cerca de 2,6 s e não deixou arquivo de sessão em `~/.claude/projects`.
- O modo `auto` depende do modelo. Com haiku, `permission_mode="auto"` nas opções é ignorado em silêncio (o `init` reporta `default`), e `set_permission_mode("auto")` falha com "Cannot set permission mode to auto: auto mode unavailable for this model". Com sonnet, o `init` reporta `auto`.
- `get_context_usage()` devolve, entre outras, as chaves `totalTokens`, `maxTokens`, `rawMaxTokens`, `percentage`, `model`, `categories`, `autoCompactThreshold` e `isAutoCompactEnabled`. Depois de um "ok" com haiku e `setting_sources=[]`: 15710 de 200000 tokens (8%).
- Subagente em segundo plano (`Agent` com `run_in_background=true`) chega como `TaskStartedMessage` com `task_type="local_agent"`. `stop_task(task_id)` depois do fim do turno encerra o subagente na hora: chega `TaskUpdatedMessage` com `patch.status="killed"`, sem `TaskNotificationMessage`.
- Mensagem enviada durante um turno autônomo (aberto pelo CLI quando um subagente em segundo plano termina) não é absorvida por ele: o turno autônomo termina com o próprio `ResultMessage`, e cerca de 0,6 s depois o CLI abre um turno separado para a mensagem, começando com um `init`. Medido com haiku e `setting_sources=[]`.
- Mensagem enviada durante um turno **normal** (aberto por mensagem do usuário) é absorvida pelo turno em andamento, sem `ResultMessage` próprio. Observado em 2026-09-30 em sessão real: 4 mensagens absorvidas em 2 turnos. Por isso a contagem de turnos pendentes só pode ser acertada depois de um prazo sem novo turno, depois de qualquer `ResultMessage`.
- Subagente em primeiro plano (`Agent` sem `run_in_background`) também chega como `TaskStartedMessage` (`task_type="local_agent"`) no mesmo instante do `tool_use`. `stop_task` durante o turno o encerra: chegam `TaskUpdatedMessage` com `patch.status="killed"` e `TaskNotificationMessage` com `status="stopped"`, e o turno principal continua até o próprio `ResultMessage`.
- Login expirado e limite da assinatura não foram provocados de verdade; a conversão das mensagens é coberta só pelos testes automatizados.

