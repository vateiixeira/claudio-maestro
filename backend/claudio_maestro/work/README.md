# Metadados de trabalho

`store.py` contém operações transacionais sobre uma conexão aberta por `db.connect`.
Não inicia sessões, não envia mensagens e não define ferramentas permitidas. A sessão
usada por uma tentativa precisa ser uma sessão normal do mesmo projeto, sem
`agent_id` legado. O chamador resolve o projeto/diretório pelas APIs existentes.

## Contrato para o runtime

- `create_item(..., project_id, title, now, source, source_instance, source_project,
  external_id, ...)` devolve `(WorkItem, created)`. A chave da fonte é composta por
  projeto local + fonte + instalação + projeto da fonte + id externo. Chamadas
  manuais sem id usam UUID e não se fundem por título.
- `update_item(item_id, expected_revision=..., now=..., ...)` altera metadados por
  comparação de revisão. Não aceita concluir diretamente uma tarefa.
- `claim_attempt(item_id, expected_revision=..., session_id=..., now=..., role=...,
  resources=...)` reserva tarefa, sessão e todos os recursos na mesma transação.
  O papel é responsabilidade, sem configuração própria de ferramentas.
- Antes de enviar, `mark_dispatching`; após admissão comprovada, `mark_running`.
  Em falha comprovadamente anterior ao envio (`send_started=False`),
  `restore_unsent` permite retentar a mesma tentativa. `mark_uncertain` conserva
  reserva e identidade; não tem retorno automático à fila por timeout/reinício.
- `record_result(..., result_kind, result_ref, now)` registra a referência de um
  arquivo já escrito pelo serviço. Pode ser chamado durante o turno e conserva
  estado e recursos; repetir a mesma referência não duplica o evento.
- `finish_attempt(..., outcome, result_kind, result_ref, now, turn_ended=True)` é
  exclusivo do serviço após comprovar ausência de turno e subagentes ativos.
  Retorna `(Attempt, is_current)`. Sucesso vai para revisão; um resultado de
  revisão antiga é conservado, mas não aceito como atual. O serviço da fase de
  revisão valida parecer, autoria e revisão alvo antes de concluir a tarefa.
  `result_ref=None` só é permitido para falha/cancelamento com fim comprovado e
  motivo explícito; nunca serve como entrega bem-sucedida sem evidência.
- `list_events(..., pending_only=True)` lê avisos duráveis ainda não confirmados.
  `ack_event` pode participar da transação do consumidor que cria o anúncio;
  não confirma por si só que o modelo recebeu um turno. Chave do anúncio é o id
  imutável do evento. O consumidor deve reler os pendentes após reinício.
- `bind_coordinator(project_id, session_id, now=...)` devolve a conversa canônica
  do projeto (a primeira associação válida vence). `coordinator_session` a lê.

Resultados extensos, instruções e transcrições nunca vão para estas tabelas.
`result_ref`, quando presente, é somente um nome de arquivo privado; a gravação
atômica e a validação desse arquivo pertencem ao serviço de execução. Falha de
gravação impede registrar/aceitar sucesso. Falha sem documento só pode ser encerrada
com motivo explícito e prova de fim; reservas nunca são liberadas antes dessa prova.

As operações de escrita de nível superior possuem sua própria transação.
`create_item_in_transaction` e `reset_signals` são helpers explícitos que exigem a
transação do chamador; permitem, respectivamente, criar tarefa+dossiê+admissão e
reservar um envio+seus sinais no mesmo commit. `ack_event` também pode participar
da transação que cria o anúncio. Não envolver as operações que já possuem transação
própria numa segunda transação.

## Serviço de execução

`WorkService(db_path, sessions=SessionManager(...), files=WorkFiles(...), publish=...)`
usa sessões normais de projeto, sem `agent_id` nem políticas de ferramentas
por papel. O `SessionManager` deve receber `context_setup=service.session_context`
e os callbacks `on_session_result`, `on_session_turn_end` e `on_session_error`.
O primeiro grava `{is_error, terminal_reason}` de cada `ResultMessage`; o segundo
confirma quiescência. Sem recibo positivo durável, `closed` e `turn_open=False`
não bastam para aceitar uma entrega após reinício.

- `coordinator(project_id)` retorna `SessionRecord` da conversa persistente.
- `create_item(project_id=..., title=..., objective=..., acceptance='', role=...,
  source=..., source_instance=..., source_project=..., external_id=...,
  source_revision=..., ready=True)` cria tarefa+dossiê+estado inicial+evento+modo
  numa transação. `delegate(session_id, **mesmos_campos)` é assíncrono e exige CTO.
- `start(item_id, expected_revision=...)` admite tarefa pendente para execução.
- `dispatch_once()` reserva uma sessão própria e envia no máximo um trabalho;
  `run()` acompanha a fila respeitando o pool e as reservas de recursos;
  `shutdown()` só encerra esse acompanhamento.
- `conclude(session_id, result_kind=..., summary=..., evidence=[], tests=[],
  next_action='', blockers='')` salva documento privado antes da referência.
- `get_work(session_id, item_id)`, `list_work(session_id)`, `dossier(item_id)` e
  `result(attempt_id)` permitem consulta. Documento perdido retorna diagnóstico
  explícito; jamais é convertido em evidência de sucesso.
- `session_identity(session_id)` e `session_catalog()` expõem papel, projeto,
  tarefa e tentativa para o catálogo do frontend, sem atribuir `agent_id`.
- `reconcile()` aplica somente resultados com prova durável de fim e sem
  subagentes ativos; `recover()` é chamado depois de `reattach_all()`.
- `send_message(session_id, text, images=None)` centraliza mensagens gerenciadas.
  Continuação de trabalhador reserva um novo envio na mesma tentativa antes do
  SDK. Envio incerto é pausado e não reenviado; `False` comprovado exige retomada
  explícita. Tentativa encerrada não recebe mensagens silenciosamente.
- `activate_project`, `deactivate_project`, `pause_project`, `resume_project` e
  `project_mode` controlam admissão. `can_legacy_dispatch(conn, project_id)` é
  uma leitura para a transação do despachante legado; não abre transação aninhada.
  O integrador deve fornecer `legacy_busy(conn, project_id)` com os estados em
  memória e os recebimentos legados que também impedem a transição.
- `assert_deletion_allowed(project_id=... ou session_id=...)` deve rodar antes
  de fechar/remover sessões ou projetos; envio incerto conserva suas reservas.

`max_tasks` limita tarefas admitidas (`ready/active/waiting/review`), sem contar
backlog, gerações técnicas de coleta ou histórico.
`max_attempts` limita tentativas por papel e entrada material da tarefa; atingir
esse limite bloqueia somente ela. Autor e revisão têm orçamentos separados, e
reavaliar uma entrada conserva o histórico sem consumir um limite histórico permanente. `max_seconds` limita a duração de cada turno enviado; a interrupção independe
conseguir escrever um relatório em disco. Checkout é reservado pelo serviço;
`resource_keys(project)` permite acrescentar bancos de teste compartilhados.

O servidor MCP `maestro_work` acrescenta `delegate_work`, `get_work`, `conclude`
e `request_decision` sem filtrar as ferramentas normais do projeto. A identidade
vem da sessão capturada no servidor. As seções de revisão/decisões e continuidade de PR abaixo descrevem a aceitação
independente, o contrato de resposta humana e seus recibos duráveis.
## API e ciclo de vida

O app constrói o serviço antes de religar as sessões, conecta os callbacks de
contexto/resultado/fim/erro e chama `recover()` após a reanexação. Seu acompanhamento
faz parte das tarefas do processo existente. Mensagens e saídas do terminal de
sessões gerenciadas passam por `send_message`; finalização manual não encerra
implicitamente uma tentativa ativa ou incerta.

- `GET /api/work-items?project_id=&status=&source=&limit=100&offset=0` retorna
  `{items, total, limit, offset}`. Os filtros são aplicados antes da paginação.
- `POST /api/work-items` recebe projeto, título, objetivo, aceite, papel inicial,
  proveniência e `ready`; retorna a tarefa canônica. Objetivo/aceite ficam privados.
- `GET /api/work-items/{id}` retorna `{item, dossier, attempts, events, dependencies}`.
  Cada tentativa inclui `result`; documentos ausentes geram `unavailable`, sem
  transformar falta de evidência em sucesso nem impedir a leitura do histórico.
- `PATCH /api/work-items/{id}` exige `expected_revision`. Metadados e referência
  do dossiê mudam na mesma transação; `update_item_in_transaction` é o helper
  explícito que permite essa composição. Alterar entrada invalida resultado antigo.
- `POST /api/work-items/{id}/start` exige `expected_revision` e retorna aceitação.
- `GET /api/work/sessions` retorna mapa por `session_id` com `work_role`, projeto,
  tarefa e tentativa. A UI pode separar trabalhadores das conversas manuais.
- `POST /api/projects/{id}/cto` abre ou retoma a mesma conversa do projeto,
  devolvendo `{session_id, project_id}`; não inicia um turno.
- `GET/POST /api/projects/{id}/work-mode` consulta ou altera `enabled/paused`.
  Ações: `enable`, `disable`, `pause`, `resume` e `cancel_delete`.

Gates legados ficam dentro das transações de admissão/reserva, incluindo projetos
adicionais e o projeto persistido da sessão histórica. A ativação considera fila,
incerteza, comentários e estado em memória; editar a configuração não apaga a
proveniência de execuções anteriores. O agendador adia ocorrências enquanto o
CTO assume o projeto, sem consumir o horário nem tentar despachá-lo repetidamente.

### Exclusão de projeto

Antes de aguardar o fechamento de sessões, a API reserva uma cerca durável em
`work_project_fences`. Create/start/CTO/send, claims e legado recusam nova admissão;
nenhuma transação SQLite permanece aberta durante o `await`. Sucesso no DELETE
remove a cerca por cascade. Falha ou reinício conserva o recibo, sem expiração.

`GET work-mode` então também retorna `deleting`, `fence_id` e `reason`. A pessoa
pode retomar `DELETE /api/projects/{id}?fence_id=<recibo>` ou usar `cancel_delete`
com o `fence_id` atual, depois de conciliar trabalho ativo/incerto. Um recibo antigo
não cancela uma exclusão nova. A reserva de um pedido ainda em execução não pode
ser cancelada por outro pedido concorrente.

O dispatcher também respeita `MAESTRO_WORK_DISPATCHER`: `0` impede `dispatch_once`
de iniciar trabalho mesmo se houver fila pronta persistida. Sem override explícito,
acompanha `MAESTRO_SPECIALISTS_SCHEDULER`, preservando a configuração segura de
instância isolada com cópia do banco. `GET /api/work/runtime` informa
`dispatcher_enabled` e o snapshot do `pool`. Isso não transforma mensagens manuais em automatismos nem
libera envios incertos. No E2E, somente a opção de chat falso habilita o dispatcher.

A reconexão automática de Remote Control passa por admissão própria, inclusive
após aguardar leitura do histórico. Sessões de trabalho não reiniciam processos
com dispatcher desligado; legadas respeitam agendador, modo e cercas dos projetos
principais/adicionais; conversas manuais respeitam sua cerca.
`MAESTRO_REMOTE_RECONNECT=0` desliga somente esse startup/retry automático também
para conversas manuais e completa a receita segura para cópias. O padrão continua
ligado; mensagens e ativações manuais seguem explícitas e operacionais.

Mudanças de projeto/adicionais de especialistas mantêm o lock do proprietário
e o escopo antigo até todos os clientes comprovadamente ociosos serem fechados.
A transação revalida a ausência de nova fila antes de alterar o cadastro. Exclusão
de projeto adicional verifica também seus proprietários e fecha os contextos
cacheados antes de podar referências. Busy/incerto exige conciliação; apagar
metadados nunca é usado como revogação de um processo ainda vivo.

Essa mutação mantém também um marcador explícito por proprietário até o commit,
distinto do lock da fila (um dispatch legítimo também usa esse lock). Controles
de SDK e reconexões automáticas recusam o marcador. Uma admissão síncrona final,
após os awaits e antes da factory de nova conexão, revalida sessão/projeto, fences,
modo CTO, estado da tentativa e escopo legado completo. A reanexação de um processo
já mantido pelo agentd preserva contexto/MCP e permite inspecionar ou conciliar
trabalho cercado ou incerto, sem iniciar outro processo nem enviar turno. Assim,
Remote Control ou uma reconexão atrasada de modelo/esforço não recriam o contexto
antigo entre o fechamento do SDK e a alteração dos projetos adicionais.

## Coleta delegada de fontes (fase 3)

`create_collection(project_id, source, source_instance, source_project, query='')`
cria uma geração efêmera de coleta e uma tarefa técnica na mesma transação que o
modo, o evento e o dossiê privado. `source` aceita `sentry` ou `kbgen`. O dispatcher
usa uma sessão normal do projeto, com responsabilidade `investigator` e dossiê
`kind=collection`; não cadastra um especialista nem altera ferramentas, MCPs,
credenciais ou permissões. O prompt desta sessão pede somente descoberta e não
alteração de código. Não há um novo sandbox de comandos por papel.

O CTO usa `collect_source` para iniciar essa sessão separada. Uma fonte que só
retorna corpos completos pode ser consultada pelo coletor: tais respostas ficam
na conversa dele, nunca são copiadas automaticamente para o CTO. `publish_collection`
captura sessão, tarefa, projeto e identidade composta da fonte no servidor. Seu
contrato fechado é:

```json
{
  "items": [{
    "external_id": "50", "title": "Rastrear guardas", "priority": "normal",
    "source_revision": "2026-10-25T12:00:00Z", "url": "https://issues.example/50"
  }],
  "cursor": "", "next_cursor": null
}
```

Cada item aceita ainda `expected_revision` local para confirmar uma substituição
após conflito; `get_source_metadata(external_id)` permite ao coletor reler somente
os metadados no escopo capturado, sem consultar dossiês de outras tarefas. Campos extras, inclusive descrição, stack e corpo, são rejeitados.
Títulos têm até 160 caracteres; id/revisão até 200; URL HTTPS até 1000, sem
credenciais. Há no máximo 25 itens por página, 100 páginas por geração e 2000
metadados de fontes por projeto. Os cursores têm até 500 caracteres e não podem
repetir uma página com conteúdo diferente nem formar ciclo. Ultrapassar limite
mantém a coleta incompleta; refine o filtro antes de iniciar outra geração.

Página repetida com o mesmo conteúdo retorna seu recibo sem duplicação. Página,
links, tarefas canônicas e referências de dossiês são atômicos: falha de arquivo
ou SQL reverte todos os registros da página. Arquivos são privados (`0600`) e
substituídos atomicamente. Uma falha SQL posterior pode deixar um arquivo privado
órfão, nunca uma tarefa canônica sem dossiê. A identidade da issue não depende da
geração: projeto local + fonte + instalação + projeto externo + id externo.

A publicação final (`next_cursor=null`) aceita zero issues e registra um resultado
técnico com recibo privado. Só o serviço encerra essa tarefa de coleta como `done`,
após Result positivo, quiescência comprovada e validação do recibo final. `conclude`
livre não substitui o recibo. Result negativo/interrupção ou recibo perdido não
confirma coleta. Uma investigação/implementação de issue continua indo a `review`.

Issues coletadas entram em `backlog`. Backlog e tarefas técnicas de coleta não
consomem `max_tasks`: o teto de executores conta `ready/active/waiting/review`.
`start_work(work_item_id, expected_revision)` captura o CTO e admite a issue;
`reevaluate_work(work_item_id, expected_revision, reason, code_reference)` reabre a
mesma entrada após mudança no código, inclusive com revisão externa idêntica.
Entrada e dossiê mudam por CAS; dossiê anterior e tentativas antigas permanecem.
O snapshot de revisão capturado no início da coleta impede sobrescrever uma
reavaliação concorrente. Revisão externa diferente invalida parecer anterior,
mas não encerra o único executor ativo nem cria outro. Uma página aceita
emite `work.changed` mesmo sem mudar a revisão, para invalidar consultas da UI.

`get_work` retorna metadados e referências, sem corpos dos resultados; omitir id
retorna `{items,total,limit,offset}` (padrão 25, máximo 200). `get_work_evidence`
carrega dossiê/resultados de uma única tarefa sob demanda, com validação de escopo.
`conclude` aceita `delivery_type` opcional: `investigation_complete`,
`implementation_complete`, `technical_followup`, `product_decision`,
`policy_blocked`. Isso descreve a entrega, sem alterar papel ou permissão. Uma
lacuna técnica continua em revisão; análise completa não exige PR artificial.

API HTTP (protegida pelo mesmo Host/Origin/X-Maestro do app):

- `POST /api/projects/{id}/collections` recebe `{source,source_instance,source_project,query?}`;
  retorna `202` com geração, tarefa técnica, cursor, estado e página de links.
- `GET /api/projects/{id}/collections?limit=25&offset=0` retorna
  `{items,total,limit,offset}` de gerações.
- `GET /api/projects/{id}/collections/{collection_id}?limit=25&offset=0`
  retorna `{id,work_item_id,source,source_instance,source_project,cursor,finalized,total,
  created_at,project_id,status,items:[{work_item_id,source_revision}],limit,offset}`.
  `finalized` indica publicação final; `status=done` comprova também fim positivo.

Não há cliente HTTP específico para Sentry/KBGen nem nomes externos de MCP
presumidos; disponibilidade e autenticação vêm do projeto. Publicação não prova
que a fonte devolveu tudo: o coletor precisa consultar e declarar o fim de forma
fundamentada. Feed/outbox ao CTO, despertar automático e revisão/decisões usam os
contratos seguintes; a ponte de PR conserva a origem entre novas tentativas.

## Revisão independente, decisões e feed (fase 4)

`reconcile()` encerra explicitamente o cliente SDK somente depois de Result durável
positivo e quiescência comprovada, incluindo Bash/subagentes. A reserva permanece
entre autor, revisor e retrabalho da **mesma** tarefa. `claim_attempt(transfer_from,
on_claim)` transfere recursos e registra o vínculo na mesma transação, sem duas
tentativas ativas. O histórico encerrado recusa novas mensagens; o CTO persiste.
Falhas de envio incertas continuam sem replay automático. O orçamento conta autores
separadamente dos revisores; quatro etapas normais não consomem quatro retries.

O autor usa `declare_workspaces(workspaces=[...])` para informar até quatro raízes
Git; o backend comprova projeto/subrepositório/worktree e reserva cada caminho.
Omitir usa somente a raiz Git do projeto: projetos sem raiz única precisam declarar
o escopo. O SDK continua em `Project.path`, preservando MCPs/configuração normais.
Após fechar o autor, o backend captura cada alvo completo com `capture_target`.
Captura incompleta bloqueia o binding de revisão e conserva a reserva; não vira
hash de conteúdo truncado. O snapshot privado tem orçamento separado de 64 MiB;
dossiês/resultados permanecem limitados a 64.000 bytes. Cada alvo conserva os
limites de 8 MiB, 1.000 arquivos, 15 s e 16 MiB de metadados do capturador.

`work_review_bindings` associa autor, sessão nova do revisor, revisão de entrada,
dossiê e snapshot. `get_review_evidence()` mostra somente essa issue.
`submit_review(binding_id, disposition, summary, evidence)` aceita `approve`,
`return`, `technical_followup` ou `ask_human`. Perguntar exige também `question` e
`action` concretas e cria o pedido humano. O revisor usa ferramentas normais e
recebe a responsabilidade de não editar. O backend recaptura os alvos depois de
fechá-lo e só aceita a mesma entrada e os mesmos digests. Autor não aprova a si
próprio. Lacuna técnica retorna à investigação; análise completa pode terminar
sem PR. `conclude` com categoria de produto/política exige usar `request_decision`.

Testes estruturados usam `{executed,status,command,output_ref}`; `status` aceita
`passed/failed/not_run/unverified`. `output_ref=tool:<tool_use_id>` aponta para
ToolUse concluído **da própria sessão**, conferido pelo backend. Para Bash, o
comando precisa corresponder exatamente. `tool_name` e `check_type=test/ci/check`
são opcionais para ferramentas/MCPs/CI normais do projeto. O backend guarda
`execution_verified`, nome, entrada limitada, digest e trecho do ToolResult.
Somente um comando Bash síncrono terminal pode receber essa comprovação genérica;
background, timeout, cancelamento, leitura/busca e MCP sem contrato de provedor
verificado ficam `unverified`, com `declared_status`, `declared_executed` e motivo.
A saída continua preservada como evidência. O revisor confere se comando e saída
sustentam o teste alegado. Para GitHub Actions há o recibo oficial abaixo. Strings legadas ficam `unverified`. Implementação exige
evidência, recibo de execução e parecer independente; análise exige evidência
e parecer. Não há allowlist nova nem executor especial de comandos.

`request_decision(question, action, options=[], evidence=[])` salva pergunta, ação
exata, tarefa/tentativa/revisão, dossiê e alvo em `work_decision_requests`.
`answer_decision(id, expected_revision, receipt, answer)` é exclusiva da API humana
protegida; nenhuma ferramenta MCP aceita resposta. O recibo é idempotente e não
pode mudar de conteúdo nem ser usado em outra decisão. Entrada/alvo alterado
expira o pedido. Resposta anterior ao fim do turno fica salva, sem liberar recursos.
Depois do fim comprovado, uma tentativa nova recebe checkpoint e resposta com o
escopo exato; vínculo/recursos ficam reservados antes do envio. O alvo é conferido
outra vez imediatamente antes do SDK. `False` pausa explicitamente; envio incerto
não é repetido. Histórico de pedidos/respostas e tentativas continua disponível.

`persist_notifications()` cria `work_notifications(event_id UNIQUE,...)` e confirma
`ack_event` na mesma transação. O feed existe mesmo com modelo ocupado/desligado.
`seen_at` significa leitura humana; `model_received_at` só recebe recibo de Result
positivo do CTO, separadamente da admissão de envio. A outbox reserva
`queued→dispatching→sent`; falha comprovada é `unsent`, falha incerta é `uncertain`.
Restart converte `dispatching` e envios `sent` ainda sem Result positivo em
`uncertain`, sem replay. O despacho automático e
a mensagem manual compartilham o lock por CTO, independente do lock do trabalhador.
O payload é limitado a vinte resumos/referências e rotulado como dados, nunca
como autorização humana. Acks não criam eventos novos. Dispatcher desligado,
pausa, cercas e legado impedem despertar automático; feed continua consultável.

APIs para a interface (mesmas proteções Host/Origin/X-Maestro do app):

- `GET /api/work/decisions?project_id=&item_id=&pending_only=true`: `{items}` com
  pedido, resposta e referências; `pending_only=false` conserva histórico.
- `POST /api/work/decisions/{id}/answer`: `{expected_revision,receipt,answer}`;
  retorna `202` com recibo. Resposta antiga ou contexto alterado retorna `409`.
- `GET /api/work-items/{id}/reviews`: `{items}` de bindings. O detalhe da tarefa
  também inclui `reviews` e `decisions`, além de dossiê/tentativas/eventos.
- `GET /api/work/notifications?project_id=&after=0&limit=100&latest=false` ou
  `GET /api/projects/{id}/work-feed`: `{items,after}`. Cada anúncio inclui CTO,
  tarefa, tentativa, evento, resumo, estado de envio e recibos separados.
  `latest=true` seleciona os avisos mais recentes e os devolve em ordem de id;
  `after` continua sendo o cursor da última linha retornada.
- `POST /api/projects/{id}/work-feed/seen`: `{through}` confirma leitura humana.
- `POST /api/projects/{id}/work-feed/retry-unsent`: retomada explícita somente de
  envios comprovadamente não iniciados; incerteza exige conciliação.

O retorno de PR usa o adaptador separado; esses vínculos não criam especialistas
fictícios. As permissões nativas do SDK continuam no fluxo normal existente.


## Recibo de execução do GitHub Actions

`verify_ci_run(run_url)` é uma ferramenta de leitura para a tentativa executora
capturada no servidor. Não aceita identidade, projeto, caminhos, SHA, estado ou
JSON fornecidos pelo modelo. O backend consulta o GitHub pela implementação
existente de `GhRunner`, com argumentos em lista, `--hostname github.com`, método
GET e endpoints construídos a partir de uma URL estrita
`https://github.com/<dono>/<repo>/actions/runs/<id>`. Ela não inicia, publica,
repete ou cancela workflows; executar testes via MCP continua permitido.

Antes de cada consulta, o adaptador revalida projeto, tentativa, revisão da
entrada, dossiê, modo, pausa, cerca de exclusão, caminho Git comprovado e reserva
do checkout. O `remote origin` precisa corresponder ao repositório da URL. A
consulta usa as credenciais já configuradas do `gh`; o login que filtra comentários
de PR não limita workflows executados por bots. Falha de consulta, autenticação,
caminho, captura ou limite não produz recibo nem vira evidência de sucesso.

Apenas `completed/success`, com `head_sha` igual ao HEAD capturado pelo backend,
pode produzir recibo. Todos os workspaces declarados devem ter captura completa,
sem alterações staged/unstaged ou arquivos não rastreados; arquivos ignorados
continuam fora do contrato Git do capturador. O remote deve identificar exatamente
um desses workspaces. As outras raízes permanecem no snapshot, mas a CI comprova
somente os jobs do repositório informado. Não se deduz equivalência de ambiente
local/remoto nem cobertura dos critérios pelo nome do workflow.

São lidos o run, os jobs da sua tentativa numérica e o run novamente: mudança de
`run_attempt`, SHA, estado ou identidade durante a verificação invalida o resultado.
Os jobs/etapas precisam estar terminais e sem falhas, com pelo menos um job e uma
etapa executados com sucesso. Há no máximo 100 jobs, 400 etapas, 256.000 bytes por
resposta, 12 recibos por tentativa e o limite privado habitual de 64.000 bytes por
documento. Sem paginação silenciosamente truncada: ultrapassar esses limites
impede a comprovação. O adaptador guarda resumo dos jobs/etapas, não baixa logs.
O revisor ainda verifica se essas etapas cobrem o aceite da tarefa.

A resposta contém `output_ref=ci:<nome>`, `command`, SHA, tentativa oficial e estado
comprovados. Use esses `output_ref` e `command` em `conclude.tests`, com
`executed=true`, `status=passed` e `check_type=ci`. O backend consulta
`work_ci_receipts`, confere ator/tentativa/entrada e digest do documento privado;
JSON parecido ou arquivo lido por uma ferramenta não emite recibo. A aceitação
independente compara o alvo do recibo com o snapshot final da revisão e recaptura
o código: CI de commit antigo não comprova patch novo, mesmo se o novo patch
ficou estável durante a revisão. Outros provedores MCP/CI permanecem evidência
externa `unverified` até existir um contrato verificável próprio.


## Continuidade de PRs das tarefas

`WorkPrIntegration` registra o callback de criação de PR com a sessão capturada.
A validação posterior liga projeto, tarefa, tentativa, workspace declarado e remote
GitHub; o diretório do SDK não é usado como prova do workspace. Sessões, claims,
bindings e dossiê são reservados atomicamente na admissão de uma tentativa, sem
uma sessão órfã se a reserva falhar.

A ponte recebe somente comentários do login configurado em PRs conhecidos, pelo
webhook assinado existente ou por consulta `gh`. Comentários ficam em documentos
privados e são dados externos. Cada lote tem identidade persistida; o recibo de
`work_pr_inbox` liga lote, tarefa e tentativa nova antes do envio normal ao SDK.
Não se continua uma sessão histórica arbitrária nem se entrega o comentário a
outro item pelo título ou pela sessão mais recente.

Crash após admissão é conciliado pelo recibo, sem criar outra tentativa. Resposta
comprovadamente negativa permite nova admissão; exceção, recibo perdido ou entrega
incerta conserva o lote, sem replay por timeout. Modo, pausa, recursos, quota e
cercas são revalidados antes da admissão e das consultas externas. Registros de PR
pendentes e comentários/lotes em fila ou incertos bloqueiam exclusão e troca de
modo para preservar a proveniência. Histórico entregue não bloqueia a troca.

`GET /api/work-items/{id}` inclui `pull_requests` com origem, tentativa atual,
contagens de comentários e estado de entrega, sem devolver todos os corpos
privados. Mudanças nesses recibos invalidam a visão da UI mesmo se a revisão da
tarefa não mudou. O fechamento da interface ou um aviso por WebSocket não é um
recibo de envio ao modelo.

## Capacidade e recursos

O limite persistido começa em um trabalhador global e um por projeto, com teto de
dois. A configuração avançada distingue limite global, padrão por projeto e
exceção de projeto; aumentar capacidade é explícito. A conversa do CTO não ocupa
uma vaga de trabalhador. A capacidade é separada das reservas de checkout e dos
identificadores de recursos compartilhados, como banco/schema de teste ou arquivos
de infraestrutura. Worktrees diferentes não isolam esses recursos.

Permissão nativa, turno aberto e espera com possibilidade de Remote Control
continuam ocupando capacidade. Só uma decisão humana persistida, após resultado
positivo, quiescência e fechamento comprovado do SDK, permite suspender a vaga;
a tarefa conserva seus recursos. A retomada readquire capacidade antes do próximo
envio. Reduzir o limite não interrompe processos; impede novas admissões até a
ocupação cair. Envio incerto conserva vaga e claims, inclusive após reinício.

`GET /api/work/runtime` devolve `dispatcher_enabled` e `pool`, com `revision`,
`global_limit`, `default_project_limit`, `project_limits`, `resource_config`,
`maximum=2`, `occupied`, `workers`, `suspended` e a política de recursos. As listas
são limitadas; a ocupação é calculada dos estados persistidos, não de um contador
exclusivamente em memória.

`PATCH /api/work/pool` exige `expected_revision` e aceita `global_limit`,
`default_project_limit`, `project_id`, `project_limit` e `resources`. A API tem as
mesmas proteções Host/Origin/X-Maestro. Mudança concorrente retorna `409`; valores
fora de 1 ou 2 são recusados. `resources` aceita até 16 identificadores de até
160 caracteres, sem caminhos nem segredos, persistidos com prefixo `shared:`.
O projeto não pode trocar sua configuração de recursos enquanto houver execução
ou reserva. Diminuir limites conserva processos e ocupação existentes.

A migração aditiva começa com os dois limites em 1 e conserva sessões, agentes,
conversas e recibos anteriores. O ensaio de transição é feito em banco temporário,
sem downgrade destrutivo nem migração automática do histórico de especialistas.
O check integral da entrega DEV está concluído, conforme o plano local. Nenhuma
passagem de tempo libera claims ou transforma envio incerto em trabalho pronto.


## Correlação de envios e confirmação de fechamento

Antes de enviar, o Maestro persiste um UUID da mensagem. A comprovação posterior
exige o eco correspondente no mesmo cliente e geração, junto do Result
correlacionado; evento tardio ou estado `idle` isolado não comprovam aquela
execução. A conciliação pode aproveitar prova tardia válida do mesmo envio,
sem repetir a mensagem ou criar outra tentativa.

O fechamento mantém recibo durável: `closing` é gravado antes do await, `closed`
só após confirmação; cancelamento, crash ou falha conservam a incerteza,
a capacidade e os recursos. `POST /api/work-attempts/{id}/reconcile-close`
concilia somente esse fechamento, pelo cliente exato retido ou por resposta
autoritativa do agentd de identidade persistida. Devolve `attempt_id`,
`process_closed` e `needs_resume`; não é uma ação de apagar estado incerto,
não reenvia trabalho e conserva a pausa do projeto.

O nonce da instância do agentd impede usar um daemon substituto como prova do
processo original. Socket ausente, daemon inacessível ou registro antigo sem nonce
não comprovam a morte do processo. Na falta de prova, o estado continua incerto.
Um daemon antigo pode exigir reinício coordenado numa adoção futura, preservando
as sessões em uso. Nesta implementação só foram usados clientes falsos e recursos
temporários; nenhum daemon ou serviço real foi alterado ou testado.

Os caps deste piloto são operacionais: tarefas admitidas, tentativas por papel e
entrada, duração de turno e vagas do pool. O uso continua registrado nas sessões.
Não há budget financeiro ou de tokens automático nem comparação real de consumo
SDK neste fechamento. Tokens acumulados não são ocupação de contexto nem gasto
exato; o piloto comparativo real permanece por executar.
