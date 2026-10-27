# Maestro centrado em tarefas e delegação


## Registro de retomada e limites da comprovação — 27/10/2026

Registro histórico das provas parciais. O fechamento DEV e as contagens do check
integral estão registrados no fim deste documento.

Esta é a cópia de entrega da worktree; o documento original do checkout principal
permanece intacto. As caixas marcadas nas fases 2/3 identificam contratos exercitados
com clientes falsos e dados temporários, não investigação das issues reais #50,
#55 ou #135. A suíte `backend/tests/work` + `test_db.py` passou com 326 testes na
integração de CI, antes do fechamento da fase 6; o controlador fará o check final.

A revisão independente aprovou CI + UI/harness: 109 testes CI/review/API/db,
47 de harness/feed, 18 Vitest focados + checagem de tipos, reproduções invertidas
e ruff. Na rodada posterior da UI, passaram 3.265 Vitest, 28 testes backend,
21 E2E focados e 20/20 testes de contexto. A revisão de marco aprovou a janela
de 50 eventos com paginação e a reinicialização do estado da conversa do CTO.
Esses resultados não substituem o `scripts/check.sh --full`, a matriz visual final
ou o veredito final do conjunto.

A revisão de ciclo de vida teve 171 testes e duas reproduções aprovados; a fase 6
está reforçando a confirmação de fechamento do SDK/agentd. Por isso o item de espera
humana na fase 4 e todas as caixas das fases 6/7 continuam pendentes. A revisão de
marco permanece em fechamento; a correção da atividade paginada com mais de
200 eventos já teve aprovação focada, sem encerrar as caixas finais da fase 7. O roteiro local é `docs/validacao/2026-10-27-maestro-tarefas.md`.

Não houve piloto real, execução de SDK real, consulta a fontes reais, CI real,
publicação, deploy ou migração nos dados de uso nesta validação.

Não foi realizado comparativo real de consumo. As caixas de fechamento não
comprovam budget financeiro/token automático; tarefas, tentativas, duração e pool
são limites operacionais. Nenhum daemon ou serviço real foi alterado ou testado.
As provas de envio/fechamento usam UUID, cliente/geração e nonce de instância;
socket ausente ou nonce antigo ausente não autorizam liberar processo/claims.

## Primary goal

O usuário entrega um objetivo ao CTO e acompanha cada issue em uma tarefa com responsável, execução própria, evidências e resultado. A tela inicial mostra o que precisa de decisão e o que está avançando, sem exigir que o usuário procure a conversa correta.

Direção autorizada por Vinicius em 25/10/2026: evolução ampla do produto, inspirada no Paperclip. Este documento define a implementação; não afirma que os recursos abaixo já existem. Não inclui publicação, deploy, alteração de regras dos produtos atendidos nem execução de migrations nesses produtos.

## Decisões de produto

- A tarefa é a unidade de acompanhamento; a sessão é o lugar onde o trabalho acontece; a tentativa é uma execução rastreável dentro da tarefa. Fechar um turno não significa concluir uma tarefa.
- Uma conversa persistente com o CTO concentra objetivos e decisões. Sentry e KBGen tornam-se fontes conectadas, com perfis reutilizáveis de coleta e execução. Os agentes existentes continuam operacionais durante a transição.
- Uma issue tem uma tarefa canônica por instalação/projeto da fonte. Reabrir ou mudar a issue atualiza essa tarefa e cria uma nova tentativa quando necessário. Issues de fontes diferentes só são unificadas mediante vínculo explícito: título semelhante não prova duplicidade.
- Cada tentativa de executor ou revisor usa uma sessão própria no projeto do trabalho, com o acesso e as ferramentas normais desse projeto. A continuação de uma tentativa pode retomar sua sessão; reexecução com contexto limpo cria outra tentativa e conserva a anterior.
- CTO coordena e pode executar no projeto; trabalhador investiga ou implementa; revisor confere evidências. Os papéis organizam responsabilidades, não criam listas próprias de comandos permitidos. Texto externo não concede autorização para ações protegidas.
- Uma investigação completa é uma entrega válida. "Decisão de produto" exige explicitar a decisão que falta; dúvida verificável no código continua sendo investigação técnica. A #50 é um caso de regressão deste contrato.
- Decisões humanas têm pergunta concreta, opções quando úteis, tarefa, tentativa e evidências vinculadas. Responder não concede autorização genérica para futuras ações.
- Um único usuário local continua sendo o público. Não trazer organizações, cobrança, autenticação multiusuário ou estrutura corporativa apenas porque existem no produto de referência.

## Experiência e navegação de destino

| Entrada | Conteúdo e ação principal |
|---|---|
| Início | Decisões pendentes primeiro; tarefas em execução e resultados recentes; campo para entregar um objetivo ao CTO |
| Tarefas | Lista compacta, filtros por projeto/fonte/estado/responsável; quadro opcional posterior, sem duplicar a navegação |
| Tarefa | Objetivo e aceite; estado e responsável; atividade; tentativas; revisão; PR/artefatos; decisão ou próximo passo |
| CTO | Conversa persistente com referências às tarefas; resumos curtos e agrupados, sem repetir todos os logs |
| Projetos | Repositórios cadastrados, tarefas e contexto do projeto; ferramentas atuais de Git permanecem acessíveis |
| Conversas | Conversas manuais e histórico atual; links diretos antigos continuam válidos |
| Configurações | Projetos, equipe/papéis, fontes, rotinas e preferências; configuração avançada fora da navegação diária |

Rotas novas planejadas: `/inicio`, `/tarefas`, `/tarefas/:id` e `/cto`. `/sessions/:id` e `/agentes/:id` continuam resolvendo. A mudança da raiz para `/inicio` só entra junto da tela funcional; não redirecionar antes. Na fase inicial, CTO é uma função do runtime existente, sem inventar um segundo motor de conversa.

Linguagem visual: leitura em primeiro lugar, lista e linha do tempo como padrão, superfícies neutras, estados por texto/ícone/cor, evidência expandida sob demanda. Desktop priorizado; decisão e acompanhamento funcionam em 375/430 px. Preservar fontes, temas, foco visível e redução de movimento existentes; usar `impeccable` na implementação visual.

## Modelo de domínio proposto

Os nomes desta seção são contratos propostos, não APIs existentes.

| Entidade | Responsabilidade |
|---|---|
| `work_items` | Identidade da tarefa, projeto de execução, responsável, fonte/id externo, título, prioridade, estado, fase, revisão e tarefa pai opcional |
| `work_attempts` | Papel/perfil, tarefa, sessão, execução existente vinculada quando aplicável, origem do acionamento, reserva atômica, estado de envio, início/fim e resultado |
| `work_events` | Histórico imutável de transições e proveniência; chaves de evento para impedir duplicação de avisos; cursor/recibo durável de entrega ao CTO |
| `work_dependencies` | Dependências explícitas entre tarefas, sem ciclos e sem trocar implicitamente o projeto de execução |
| `work_decisions` | Pedido humano, ação exata, versão/revisão alvo, resposta, responsável e momento; resposta expirada quando o contexto material muda |
| `work_resource_claims` | Exclusão por tarefa, checkout e recursos compartilhados; reserva por tentativa, nunca apenas por agente |

SQLite guarda metadados e referências. Dossiês, prompts, snapshots e relatórios extensos ficam em arquivos privados da pasta de dados, com escrita atômica e permissão 0600; transcrições continuam em `~/.claude/projects`. Limites de tamanho e proveniência acompanham material externo. Uma falha de escrita não pode produzir tarefa concluída sem evidência.

Estado da tarefa: `backlog`, `ready`, `active`, `waiting`, `blocked`, `review`, `done`, `cancelled`. Fase separada: investigação, implementação, teste ou revisão. Motivo de espera separado: usuário, aprovação, dependência, recurso ou execução incerta. Estado da tentativa descreve despacho e execução, sem confundir fila com trabalho realizado.

Uma tentativa só pode reivindicar tarefa elegível em transação `BEGIN IMMEDIATE`, com verificação de versão. Índice/constraint impede duas tentativas executoras ativas para a mesma tarefa. A sessão e a reserva são persistidas antes do envio. Confirmação comprovadamente negativa permite devolver à fila; envio incerto exige conciliação, nunca repetição automática por timeout. Reinício não libera reserva só por idade.

## Phase 0 — Descoberta e contrato de referência

**How this serves the primary goal:** garante que o acompanhamento use sessões reais e conserve as proteções existentes, em vez de criar uma fila apenas visual.

Leituras realizadas: `PRODUCT.md`, `CONTRIBUTING.md`, regras globais/raiz/locais, análise da rodada KBGen7, descoberta delegada do backend e fontes primárias do Paperclip. Relatório de descoberta local inclui `specialists/{service,store,files,prompt,tools,scheduler,policy}.py`, `sessions.py`, `db.py`, `app.py`, interface/falso de agente e testes de fila, conversas, ferramentas, comentários e políticas.

APIs existentes permitidas:

- `SessionManager.create_session(project, group_id=None, *, specialist_id=None, model=None, effort=None)` — `sessions.py:3595`; sessão independente. `specialist_id` instala política no caminho legado; o novo fluxo usa a montagem normal do projeto e vínculo próprio de tarefa.
- `SessionManager.send(session_id, text, images=None)` — `sessions.py:3893`; `send_started=False` distingue falha comprovada antes do envio; exceção não prova ausência de envio.
- `SpecialistService.session_setup(record)` — `specialists/service.py:186`; montagem real de prompt, ferramentas, ambiente e política por `SessionExtras` (`sessions.py:972`).
- `SpecialistService.start_run(..., defer_dispatch=False)` — `specialists/service.py:531`; fila atual deve permanecer funcional enquanto nasce o novo despachante.
- `store.claim_run(conn, run_id, session_id, now)` — `specialists/store.py:361`; copiar a reserva condicional antes do envio, não a suposição de bloqueio global por agente.
- `db.transaction(conn)` — `db.py:517`; `BEGIN IMMEDIATE`, rollback inclusive em cancelamento.
- `SpecialistService.recover()` — `specialists/service.py:1056`; após `reattach_all`, conforme `app.py:324–332`.
- `SpecialistFiles.write_run_text/read_run_text/delete_run_text` — `specialists/files.py:240/304/309`; padrão de conteúdo privado.

Referência Paperclip, consultada em 25/10/2026, sem instalar nem executar suas skills:

- [Delegação](https://docs.paperclip.ing/guides/org/delegation/) e [issues](https://docs.paperclip.ing/guides/day-to-day/issues/): responsabilidade e trabalho rastreável.
- [Acionamento por tarefa](https://github.com/paperclipai/paperclip/blob/master/server/src/services/issue-assignment-wakeup.ts), SHA de arquivo `96ec5d963183b1ff9a853170809ffe38c1377ba0`: payload identificado, ator e comentário causador.
- [Resumo de continuidade](https://github.com/paperclipai/paperclip/blob/master/server/src/services/issue-continuation-summary.ts), SHA `554c8313bab18edab60ef4faeee4ff0b5a37b82d`: checkpoint limitado por tarefa; não copiar suas inferências textuais como autoridade de execução.
- [Espera de execução](https://github.com/paperclipai/paperclip/blob/master/server/src/services/execution-wait.ts), SHA `0e749f7f766f15d7448ed42504a67efc40d8c575`: sinal de espera não inventa tentativa; agrupamento só de sinais automáticos substituíveis.
- [Lock de início](https://github.com/paperclipai/paperclip/blob/master/server/src/services/agent-start-lock.ts), SHA `38cbaf74c6e3ea93a55ae4eda645839cff54cedf`: referência de serialização; não importar a liberação por timeout para um envio incerto do Maestro.

Confiança alta nas assinaturas locais e nos quatro arquivos externos lidos. Paperclip é referência de padrões, não prova de equivalência entre seus adaptadores e o SDK do Maestro. Os limites de contexto não demonstraram a causa única das falhas: rodada7 ocupou 54,8% da janela; melhora será medida por completude e retrabalho.

- [x] Verificar APIs e padrões reais antes de definir o plano (25/10/2026).
- [x] Revisar o plano inicial independentemente e resolver lacunas de transição, entrega de avisos e reservas de recursos (25/10/2026). Complemento posterior sobre acesso normal por projeto incorporado e aprovado em nova revisão independente; ajustes de clareza sobre roteamento e seleção explícita do projeto aplicados.

## Phase 1 — Tarefas persistentes e contexto de projeto

**How this serves the primary goal:** cada issue passa a ter identidade estável, sem desaparecer numa execução de lote nem duplicar trabalho a cada coleta.

Implementar esquema aditivo e módulo de armazenamento de tarefas/tentativas/eventos. Copiar transações e testes de migração existentes em `db.py` e `backend/tests/test_db.py`; usar fixtures de `backend/tests/specialists/test_service.py:43–90`. Preservar todos os registros antigos, sem inferir tarefas a partir de títulos de sessão. Criar tarefas manuais e referências de fontes com identidade composta; fazer atualização otimista de revisão.

O projeto é a unidade de contexto e acesso, conforme complemento do Vinicius em 25/10/2026. CTO e trabalhadores usam arquivos, ferramentas, MCPs e ambiente disponíveis numa sessão normal desse projeto, sem nova allowlist de ferramentas/comandos por agente ou papel e sem interseção de políticas herdadas dos especialistas legados. Coordenador, investigador, implementador e revisor são responsabilidades e instruções de trabalho, não perfis de credenciais. O backend resolve o projeto e o diretório registrado; o papel não altera a configuração de ferramentas. Regras do projeto e autorizações de ações destrutivas/deploy continuam valendo. Não copiar segredos de outros projetos para o prompt do CTO.

O novo fluxo usa a montagem normal de sessão de projeto. Antes de implementar, separar a identidade de responsável/origem da associação legada `specialist_id`, hoje usada também para instalar políticas restritivas. Não passar pelo `session_setup` legado e depois contornar suas recusas, nem ativar bypass para simular acesso normal. A fila e as sessões legadas conservam comportamento até a transição explícita.

Verificação, com testes escritos primeiro:
- [x] Migração em banco vazio e banco de versão anterior com dados/referências; integridade e rollback (25/10/2026, commit local `be8a80f`).
- [x] Duplicação concorrente da mesma fonte/projeto/id retorna a mesma tarefa; fontes diferentes não colidem (25/10/2026).
- [x] Transição desatualizada falha sem perder resultado; eventos preservam ator, tentativa e revisão (25/10/2026).
- [x] Extensão de sessão preserva configuração normal de ferramentas, MCPs e permissões, sem allowlist legada; SessionContext e callbacks revisados, 112 testes independentes passaram (25/10/2026). A ligação com a aplicação será verificada na fase2.
- [x] Projeto/diretório é resolvido pelo cadastro; vínculos inválidos e cruzados são recusados e indisponibilidade bloqueia somente o trabalho correspondente, sem caminho fornecido pela issue (25/10/2026).

Guardas: não editar migrations publicadas; não iniciar SDK, fila ou migração no banco real nesta fase; não confundir acesso normal de projeto com ativação automática de bypass ou autorização para deploy.

## Phase 2 — Executor por issue e recuperação durável

**How this serves the primary goal:** o usuário consegue abrir a execução exata de uma issue e retomá-la sem misturar contextos ou repetir ações após reinício.

Copiar padrões de `claim_run`, `_restore_unsent`, `_uncertain_run` e `recover`. Criar despachante próprio com um trabalhador inicialmente. Manter exclusão por sessão; retirar o bloqueio por especialista apenas do novo caminho com escopo explícito, sem alterar a fila legada. Delegação retorna tarefa aceita imediatamente; o CTO não espera sincronicamente pelo filho.

Ativação por proprietário é persistida e exclusiva entre os dois despachantes desde esta fase. Antes de habilitar o novo modo, impedir novas admissões legadas e drenar ou conciliar rotinas, mensagens, permissões e comentários já em voo; uma entrega incerta impede a troca automática. Enquanto o proprietário estiver no modo novo, mensagens e comentários passam pela admissão comum, sem caminho lateral para iniciar trabalho. Desabilitar o novo modo também exige drenar/conciliar; pool igual a um não substitui essa fronteira. O caminho legado dos outros proprietários permanece intacto.

Aqui, proprietário identifica somente o roteamento/origem legada para a transição, não um proprietário de permissões. O acesso da execução nova continua vindo do projeto.

Ferramenta proposta `delegate_work` recebe tarefa, papel e revisão esperada; o backend deriva chamador, projeto, responsável e profundidade da sessão. `get_work` consulta resultado/status limitado. Estas ferramentas controlam o trabalho, sem substituir nem filtrar as ferramentas normais do projeto. Trabalhador não pode delegar recursivamente. Os caps entregues são operacionais: tarefas, tentativas por papel/entrada, duração e pool. O uso permanece registrado nas sessões; budget financeiro ou de tokens automático não foi implementado neste piloto. Estimativa de tokens não vira gasto exato. Parar ao atingir limite e informar motivo.

Verificação:
- [x] `FakeAgentFactory` comprova duas issues em sessões/contextos diferentes, sem chamada ao SDK real.
- [x] CTO ativo não bloqueia trabalhador; uma sessão nunca recebe dois turnos simultâneos.
- [x] Reinício antes/durante/depois do envio: recuperação, espera e ausência de replay incerto.
- [x] Pausa/cancelamento afetam somente o escopo escolhido; nenhuma tarefa é concluída por um `end_turn` isolado.
- [x] Testes legados de fila, comentários e permissões continuam passando.
- [x] Ativação/desativação com rotina, mensagem ou comentário em voo não cria execução concorrente nos dois despachantes; proprietário em modo legado não aceita delegação nova.

Referências: `test_queue.py` (FIFO, pausa, permissão, recuperação e partida lenta), `test_conversations.py` e `test_session_extras.py`. Guardas: sem `asyncio.create_task` como única persistência; sem timeout liberando trabalho incerto; sem criar segunda implementação de processo/SDK.

## Phase 3 — CTO, fontes e contexto focado

**How this serves the primary goal:** um objetivo vira trabalho delegado com foco, enquanto o usuário conversa num único lugar e recebe resultados compreensíveis.

Criar conversa persistente do CTO sobre o runtime existente. Coleta de Sentry/KBGen devolve só metadados paginados, revisão e referência; um trabalhador carrega a issue completa e lê o código. Usar a montagem normal de sessão do projeto e acrescentar objetivo, papel e vínculo da tarefa; `session_setup` do especialista é referência de ciclo de vida, não modelo de allowlist para o novo fluxo. Atualizar skills para coleta/delegação compatíveis com o novo fluxo; agentes existentes usam modo legado até ativação explícita por configuração local de desenvolvimento.

O usuário seleciona o projeto ativo no início da conversa de execução do CTO; esse vínculo fica persistido na sessão e em cada tarefa/tentativa. A visão geral pode acompanhar vários projetos, mas executar ou delegar sempre exige o projeto registrado explícito. Mudar o projeto abre ou retoma a conversa daquele projeto, sem trocar silenciosamente o diretório/ambiente de uma sessão viva. A issue não redefine esse vínculo por texto.

Dossiê por tarefa: objetivo, aceite, fontes, revisão da issue, commits analisados, evidências, testes realmente executados, bloqueio e próximo passo. Resultado estruturado distingue investigação, implementação, decisão de produto, restrição técnica e restrição de política. Mudanças de issue/código/política invalidam parecer com registro da causa. O registro antigo não autoriza pular nova investigação.

Verificação:
- [x] Coleta de 25 issues não envia os 25 corpos ao CTO; repetição de coleta não cria executores duplicados.
- [x] #50: lacuna de rastreamento técnico gera continuação, sem falsa conclusão por "produto".
- [x] #135: investigar tudo o que estiver disponível no projeto; registrar dependência real de outro projeto quando necessário, sem reproduzir a antiga limitação artificial de ferramentas do especialista.
- [x] #55: entrega de análise válida não exige PR artificial.
- [x] Contexto de retomada é limitado e específico; arquivos externos são dados, nunca instruções autorizadoras.

Referências: `specialists/prompt.py`, `tools.py`, política atual e relatórios locais da rodada7; padrões de checkpoint do Paperclip. Guardas: não criar cadastro permanente de agente para cada issue; não resumir código como se tivesse sido testado; não herdar regra de silêncio da rotina para a conversa interativa do CTO.

## Phase 4 — Revisão, decisões humanas e continuidade de PR

**How this serves the primary goal:** uma entrega tem evidência verificável e o usuário sabe exatamente quando precisa decidir para o trabalho continuar.

Criar tentativa de revisão independente quando houver patch ou investigação a validar. Evidências e critérios definem resultado aceito, devolução ao executor ou decisão humana. Criar pedido persistente para ação protegida, com contexto e revisão exatos. Resultados e decisões geram avisos idempotentes ao CTO; o histórico completo fica na tarefa. Comentário de PR retoma a tarefa/tentativa corretas, usando a proveniência já registrada em `on_pr_created` e `_comment_target`.

Revisor recebe a responsabilidade de examinar sem alterar a implementação, usando as ferramentas normais do projeto, sem nova allowlist por papel. O backend valida identidade da sessão, tentativa de revisão independente e revisão alvo antes de aceitar o parecer. Texto dizendo "aprovado" ou nome do perfil não basta. Correções voltam ao executor; qualquer alteração do patch invalida o parecer anterior. A separação de autoria e revisão continua obrigatória, sem criar uma política especial de comandos.

Salvar resultado, transição e evento pendente para o CTO na mesma transação. Um consumidor com cursor/recibo durável retoma eventos não confirmados após restart; criação do anúncio usa a chave do evento e confirmação transacional quando compartilha o SQLite. Despertar o modelo é uma ação separada, sujeita ao mesmo protocolo de envio incerto: anúncio persistido pode aparecer na conversa mesmo que não seja seguro repetir um turno. Não tratar WebSocket ou chamada em memória como comprovante de entrega.

Verificação:
- [x] Autor não aprova a própria entrega; resultado sem teste/evidência suficiente não é marcado como implementação concluída.
- [x] Aprovação duplicada ou para revisão antiga não dispara ação novamente.
- [x] Comentário de PR não vai à última sessão arbitrária; histórico de tentativas conserva autoria.
- [x] Espera humana não bloqueia outras tarefas; recusas e cancelamentos têm efeito explícito.
- [x] Crash entre resultado, anúncio e confirmação não perde aviso nem repete resultado; envio incerto ao CTO não é repetido automaticamente.

Referências: `test_comments.py` (proveniência/recuperação), anúncios por `run_id`, conclusão ao fim do turno. Guardas: mensagem de issue não é aprovação humana; conclusão registrada antes do fim do turno não libera recursos.

## Phase 5 — Interface centrada no trabalho

**How this serves the primary goal:** o usuário acompanha objetivos e resolve pendências pela tarefa, sem navegar entre agentes, sessões e anúncios para reconstruir o andamento.

Implementar as rotas propostas e reorganizar menu/início. Copiar infraestrutura de API, stores e reconexão atual; integrar a base local já revisada `b499bd1` de conversa persistente e subexecuções, sem perder resultados por `run_id`. Tela da tarefa reúne resumo, atividade, tentativas e evidências; abrir transcrição é aprofundamento, não requisito para entender estado. Conversas e URLs existentes permanecem acessíveis. Configuração de agente vira área de equipe/perfis/fontes progressivamente.

Verificação:
- [x] Vitest antes dos componentes; E2E de objetivo → tarefa → execução → revisão → resultado/decisão com agente falso.
- [x] Filtros/URL, foco, teclado, rascunhos e reconexão preservados; tentativa histórica não mostra conteúdo da mais recente.
- [x] Matriz 1920, 1440, 1280, 1024, 768, 430 e 375 px; revisão visual e segunda rodada de acabamento.
- [x] Estados de vazio, carregamento, erro, fila, limite, permissão, incerteza, falha e conclusão têm ação coerente.

Referências: `frontend/src/router/index.ts`, stores e `ConversationThread`, preview `b499bd1`, `PRODUCT.md` e skill `impeccable`. Guardas: não criar um dashboard de números sem ação; não esconder decisões no log; não trocar identidade do worker por nome genérico na UI.

## Phase 6 — Concorrência limitada e transição de dados

**How this serves the primary goal:** tarefas independentes avançam juntas sem disputa por checkout, banco ou aprovação e sem perder o histórico existente.

Após o fluxo sequencial passar, habilitar até dois trabalhadores independentes no piloto, com limites global/por projeto e reservas de recursos. Worktree não isola banco: declarar banco/schema de testes compartilhado, migrations e arquivos de infraestrutura como recursos exclusivos. Revisor e executor da mesma tarefa não alteram a mesma worktree simultaneamente. Dependências devem impedir ciclos e liberar somente após condição persistida.

Capacidade do pool e propriedade de recurso são controles distintos. Permissões nativas e espera com Remote Control conservam capacidade enquanto o processo puder continuar. Uma decisão humana durável só suspende a vaga depois de resultado positivo, quiescência e fechamento confirmado; as reservas de checkout/banco permanecem. A retomada exige readquirir capacidade. Não se revoga recurso de processo vivo para aumentar paralelismo.

Ensaiar em cópia consistente do banco; legacy não converte automaticamente todo histórico em tarefas. Preservar conversas/agentes/avisos existentes e permitir operação legada durante transição. Atualizar `PRODUCT.md`, README, ROADMAP e CHANGELOG com o comportamento realmente implementado.

Verificação:
- [x] Duas issues independentes avançam; mesmo recurso/tarefa serializa; bloqueio humano não ocupa indevidamente worker.
- [x] Falha/restart não perde claim nem cria segundo executor; liberação exige prova de fim ou intervenção explícita.
- [x] Ensaio de migração preserva contagens, vínculos, conteúdo privado e caminhos de retorno; não testar downgrade destrutivo em dados reais.
- [x] Agentes legados continuam agendando e respondendo a PRs; coletor novo não roda em paralelo com rotina antiga para a mesma fonte.

Referências: políticas atuais, testes de recuperação e regras de worktree/recursos do projeto. Guardas: sem paralelismo ilimitado; sem supor banco isolado por haver branch distinta; sem migração real/deploy nesta entrega de desenvolvimento.

## Phase 7 — Verificação final e piloto comparável

As caixas desta fase fecham a entrega de desenvolvimento com dados temporários e
cliente falso. O piloto comparativo com issues/SDK/CI reais é posterior e não foi
executado nem incluído como prova desta entrega.

**How this serves the primary goal:** comprova que o novo fluxo entrega trabalho mais completo e claro sem perder segurança ou confiabilidade.

Rodar verificações apropriadas (`scripts/check.sh`, suites de orquestração, E2E isolado sem build concorrente), revisão crítica por tarefa e revisão final de marco. Conferir APIs reais, ausência de bypass de política, uso exclusivo de `run_git`, Host/Origin/X-Maestro e arquivos privados. Browser/testes nunca usam o SDK real.

Pilotar somente depois da implementação validada e da autorização de uso/publicação aplicável. Comparar mesmas issues por completude, evidências, retrabalho, tempo, decisões úteis e consumo total CTO+executores+revisores; PRs isoladamente não medem sucesso. Relatar tokens acumulados separadamente da ocupação de contexto.

- [x] Backend/lint, frontend/tipos/build, E2E e revisão final passarem; falhas conhecidas explicitadas.
- [x] Evidência visual e roteiro de teste disponíveis em instância isolada; banco real não migrado inadvertidamente.
- [x] User-visible docs retratarem somente o que existe; plano e diário indicarem pendências com precisão.

## Dependências e execução

Sequência funcional: 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7. Depois da fase2 integrada e validada, a coleta/continuidade de fontes (fase3) pode ser implementada em paralelo ao capturador puro de alvo de revisão (parte independente da fase4): este só lê repositórios e usa testes Git temporários, sem editar schema, serviço, APIs ou arquivos da coleta. A integração de revisão/decisão continua dependendo da fase3. Após publicação dos contratos HTTP de revisão/decisões/feed pelo responsável da fase4, a implementação da interface (fase5) pode ocorrer em paralelo à conclusão do motor e da ponte de PR: o frontend tem arquivos e testes próprios, usa esses contratos definidos e mocks HTTP; não altera backend, scripts de E2E ou migrations. Integração ponta a ponta, build/check combinados e preview só acontecem depois de todos os módulos estarem estáveis e revisados. Estudos de interface e contratos de fontes podem ocorrer independentemente após a fase1; edição do schema, despachante e testes que disputam recursos permanecem sequenciais. Cada fase gera unidade revisável e testes antes da implementação; só marcar feita após verificação. A fase0 concluída não equivale a produto implementado.

Fora deste recorte: múltiplos provedores de modelo, multiusuário, organizações, cobrança, agentes se contratando livremente, reescrever Vue/FastAPI, importação indiscriminada do Paperclip e execução autônoma de deploy/migrations dos produtos atendidos.


## Revisão de marco antes do check integral — 27/10/2026

Veredito comunicado pelo controlador: **APROVADO, condicionado ao check integral**.
Passaram 14 casos adversariais, 632 testes backend ampliados e a rodada final de
harness (44) + workflow (1), incluindo a correção do eco do UUID original. São
escopos focados; não representam o resultado do `scripts/check.sh --full`, que
continua em execução no código congelado. Check integral, preview, commit e as
caixas finais da fase 7 aguardam as contagens e a confirmação do controlador.

### Follow-up P3 aceito

`AgentdClient.kill` confere o nonce no hello e na resposta; prova por ausência ou
listagem exige a mesma instância. A RPC de kill no servidor ainda não valida um
nonce esperado antes de produzir efeito: esse CAS do lado do servidor **não está
implementado** e fica como hardening posterior aceito pela revisão, sem bloquear
o fechamento deste piloto. Cada filho recebe UUID4 novo em `server._spawn`, sem
identificador fornecido pelo chamador; divergência de identidade nunca libera
claims. Nenhum daemon ou serviço real foi alterado ou testado nestas provas.


## Fechamento DEV após check integral — 27/10/2026

Prova comunicada pelo controlador sobre o código congelado:
`env -u VTE_VERSION scripts/check.sh --full`, saída **0**, log
`/tmp/maestro-final-check.log`.

| Verificação | Resultado |
|---|---|
| Ruff | Passou |
| Pytest | 5.060 passaram; 4 ignorados; 298,19 s |
| Vitest | 3.265 passaram |
| Tipos e build do frontend | Passaram |
| E2E completo | 191 passaram; 5,4 min |
| Revisão de marco | APROVADO; P1/P2 encerrados; follow-up P3 aceito abaixo |

Os 14 adversariais, 632 backend ampliados e harness 44 + workflow 1 são provas
focadas adicionais já comunicadas; não devem ser somados como conjuntos disjuntos
aos totais do check integral. Os testes continuam usando dados temporários,
SDK falso e respostas falsas do GitHub; nenhuma execução real do SDK ou CI é
alegada por esses números.

A matriz visual foi aberta e inspecionada nas sete larguras, sem overflow, com
segunda rodada de acabamento e teclado Enter/Escape/foco do menu móvel. As
capturas comunicadas estão em
`/tmp/maestro-work-visual-qa/tarefa-real-{1920,1440,1280,1024,768,430,375}.png`;
o E2E final repetiu a matriz e gerou capturas em `frontend/test-results/`.
Capturas e inspeção são a evidência visual; HTTP do preview é outra comprovação.

Fora do escopo comprovado: piloto comparativo com issues reais, SDK/CI reais,
comparação real de consumo e budget financeiro/token automático. O uso continua
nas sessões; os caps entregues são operacionais. Não houve migração dos dados de
uso, alteração de daemon/serviço real, publicação ou deploy. O P3 aceito continua
hardening posterior: o CAS de nonce no servidor antes do efeito da RPC kill não
foi implementado; não é apresentado como concluído por este fechamento DEV.

A confirmação do preview isolado está registrada abaixo. O commit conjunto é
responsabilidade do controlador; nenhum push está incluído nesta entrega.


## Preview isolado confirmado e conclusão DEV

Em 27/10/2026, o controlador confirmou HTTP 200 em
`http://127.0.0.1:6635/inicio` e preparou o cenário pela API do servidor com
cliente falso:

- Projeto temporário **TrabalhoDemo** (id 8), com conversa própria do CTO.
- Tarefa 1, **Investigar contrato de exemplo**: concluída, com três tentativas
  preservadas e autor/revisor separados.
- Tarefa 2, **Avaliar ajuste no contrato**: decisão humana 2 pendente, para explorar
  a resposta pela interface.

As sete capturas finais do E2E completo foram copiadas para
`/tmp/maestro-work-visual-qa`; o controlador reabriu as versões atuais de 375 e
1440 px, conferindo o estado neutro da decisão registrada e a clareza do histórico.
O HTTP confirma disponibilidade; as capturas e sua inspeção comprovam a revisão
visual. Não houve SDK nem GitHub reais nesse cenário.

No fechamento, o preview foi mantido ativo pelo controlador para quem usa conferir,
com log `/tmp/maestro-preview.log`. Todas as caixas requeridas da entrega DEV nas
fases 0–7 estão fechadas. Piloto real, comparação de consumo e budget financeiro/
tokens automático continuam fora do escopo comprovado. O P3 aceito permanece um
follow-up de hardening, sem alegar CAS de nonce já implementado no servidor.
Commit conjunto é responsabilidade do controlador; este registro não afirma que
foi feito. Nenhum push ou deploy integra a entrega.
