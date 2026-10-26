# Metadados de trabalho

`store.py` contém operações transacionais sobre uma conexão aberta por `db.connect`.
Não inicia sessões, não envia mensagens e não define ferramentas permitidas. A sessão
usada por uma tentativa precisa ser uma sessão normal do mesmo projeto, sem
`specialist_id` legado. O chamador resolve o projeto/diretório pelas APIs existentes.

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
usa sessões normais de projeto, sem `specialist_id` nem políticas de ferramentas
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
  `run()` acompanha a fila sequencial e `shutdown()` só encerra esse acompanhamento.
- `conclude(session_id, result_kind=..., summary=..., evidence=[], tests=[],
  next_action='', blockers='')` salva documento privado antes da referência.
- `get_work(session_id, item_id)`, `list_work(session_id)`, `dossier(item_id)` e
  `result(attempt_id)` permitem consulta. Documento perdido retorna diagnóstico
  explícito; jamais é convertido em evidência de sucesso.
- `session_identity(session_id)` e `session_catalog()` expõem papel, projeto,
  tarefa e tentativa para o catálogo do frontend, sem atribuir `specialist_id`.
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

`max_tasks` limita tarefas pendentes do projeto, não todo o histórico.
`max_attempts` limita tentativas por tarefa; atingir esse limite bloqueia somente
ela. `max_seconds` limita a duração de cada turno enviado; a interrupção independe
conseguir escrever um relatório em disco. Checkout é reservado pelo serviço;
`resource_keys(project)` permite acrescentar bancos de teste compartilhados.

O servidor MCP `maestro_work` acrescenta `delegate_work`, `get_work`, `conclude`
e `request_decision` sem filtrar as ferramentas normais do projeto. A identidade
vem da sessão capturada no servidor. A fase de decisões/revisão ainda deve criar
o contrato de resposta humana, aceitação independente e retorno de PR;
`request_decision` nesta camada registra a pendência e conserva a tentativa.
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
`dispatcher_enabled`. Isso não transforma mensagens manuais em automatismos nem
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
