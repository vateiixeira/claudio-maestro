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
- `list_events(..., pending_only=True)` lê avisos duráveis ainda não confirmados.
  `ack_event` pode participar da transação do consumidor que cria o anúncio;
  não confirma por si só que o modelo recebeu um turno. Chave do anúncio é o id
  imutável do evento. O consumidor deve reler os pendentes após reinício.
- `bind_coordinator(project_id, session_id, now=...)` devolve a conversa canônica
  do projeto (a primeira associação válida vence). `coordinator_session` a lê.

Resultados extensos, instruções e transcrições nunca vão para estas tabelas.
`result_ref` é somente um nome de arquivo privado; a gravação atômica e a validação
da existência desse arquivo pertencem ao serviço de execução. Falha de gravação deve
impedir `record_result`/`finish_attempt`, sem liberar claims.

As operações de escrita possuem sua própria transação, exceto `ack_event`, que
permite agrupar anúncio e recibo no mesmo commit. O consumidor não deve envolver
outras operações de escrita deste módulo numa segunda transação.
