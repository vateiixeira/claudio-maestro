# Como contribuir

Obrigado pelo interesse! Issues e pull requests são bem-vindos, em português.

## Ambiente de desenvolvimento

Requisitos: os mesmos do [README](README.md#requisitos).

```bash
uv sync
pnpm --dir frontend install
```

No desenvolvimento rodam dois processos, os dois com recarga automática:

```bash
uv run uvicorn claudio_maestro.app:app --reload --reload-dir backend --host 127.0.0.1 --port 6660   # backend
pnpm --dir frontend dev                                                                             # frontend
```

Acesse **http://localhost:6600**. O Vite repassa `/api` e `/ws` para o backend. Para mudar as portas, use `MAESTRO_PORT` e `MAESTRO_DEV_PORT` (e o mesmo valor no `--port` do uvicorn).

Para não misturar com os seus dados de uso, aponte `MAESTRO_DATA_DIR` para outra pasta enquanto desenvolve.

### Ver uma worktree ao lado do app

Para conferir uma mudança de frontend sem mexer no app que você está usando, suba um segundo Vite a partir da worktree, apontando para o mesmo backend. Ligue `MAESTRO_PREVIEW_PORT` no backend (ele passa a aceitar essa porta como do próprio app) e rode o Vite da worktree nela:

```bash
MAESTRO_PREVIEW_PORT=6610 uv run uvicorn claudio_maestro.app:app --host 127.0.0.1 --port 6660   # backend, uma vez
MAESTRO_DEV_PORT=6610 pnpm --dir <worktree>/frontend dev                                        # preview da worktree
```

Acesse **http://localhost:6610**. O preview usa os dados reais do backend: o que você fizer nele vale de verdade. Mudanças de backend da worktree não aparecem aqui; para elas, suba outra instância com `MAESTRO_DATA_DIR` próprio. Na instância isolada com cópia do banco, use `MAESTRO_ROUTINES_SCHEDULER=0`, `MAESTRO_WORK_DISPATCHER=0` e `MAESTRO_REMOTE_RECONNECT=0`, para não disparar horários, tarefas prontas nem reconexões automáticas de conversas marcadas na cópia. Quando `MAESTRO_WORK_DISPATCHER` não estiver definido, ele acompanha o valor de `MAESTRO_ROUTINES_SCHEDULER`, preservando esse modo seguro. Mensagens manuais continuam sendo ações explícitas: não as envie a sessões reais na cópia. O E2E só habilita o dispatcher com `MAESTRO_E2E_CHAT=1`, usando exclusivamente o cliente falso.

### Conferir o fluxo de tarefas sem dados reais

Para alterações no backend, prefira o servidor descartável do E2E a um Vite ligado ao app em uso. Na raiz da worktree, depois de compilar seu frontend, uma exploração com cliente falso pode usar:

```bash
MAESTRO_E2E_CHAT=1 MAESTRO_E2E_PORT=6648 uv run python scripts/e2e_server.py
```

Abra `http://127.0.0.1:6648/inicio`. O servidor monta seus próprios dados temporários e o cliente falso; o comando recusa portas dos serviços. Pare essa exploração antes do E2E automatizado. Não aponte o navegador para o backend de produção para testar objetivos, decisões ou comentários de PR. O cliente falso demonstra o fluxo, sem comprovar uma execução real do SDK, uma fonte externa ou CI.

Se uma reprodução exigir cópia consistente do SQLite, copie também os documentos privados referenciados e use uma pasta de dados própria. Mantenha `MAESTRO_ROUTINES_SCHEDULER=0`, `MAESTRO_WORK_DISPATCHER=0` e `MAESTRO_REMOTE_RECONNECT=0`; uma nova porta, sozinha, não isola os dados. Para histórico isolado, use também um `CLAUDE_CONFIG_DIR` descartável. Não envie mensagens nem ative manualmente Remote Control de sessões reais na cópia: esses controles continuam explícitos e podem iniciar processos. Não encerre o agentd da instalação em uso.

As tabelas de tarefas, revisões, decisões, feed, PRs e recibos de CI são aditivas. Não converter sessões antigas pelo título nem simular downgrade destrutivo. A exclusão exige conciliar execução e envio incerto; remover uma linha do banco não é procedimento de recuperação. As APIs e as reservas de recursos ficam documentadas em [work/README.md](backend/claudio_maestro/work/README.md).

## Testes e verificações

```bash
uv run pytest                  # backend
uv run ruff check              # lint do backend
pnpm --dir frontend test       # frontend
pnpm --dir frontend build      # compilação e checagem de tipos
pnpm --dir frontend e2e        # testes de ponta a ponta no navegador
scripts/check.sh               # só o que a mudança pede
scripts/check.sh --e2e         # o que a mudança pede, mais o E2E
scripts/check.sh --all         # tudo, menos o E2E
scripts/check.sh --full        # tudo, igual à CI
```

Sem argumentos, o `scripts/check.sh` compara o que mudou com a `develop` (commitado ou não) e roda só o necessário: mudança em `backend/`, `pyproject.toml`, `uv.lock` ou `scripts/` roda o ruff e o pytest; em `frontend/`, os testes e a compilação; em `.github/` ou no próprio `check.sh`, tudo menos o E2E; só documentação, nada. Ele diz o que vai rodar e por quê, e roda todas as verificações escolhidas mesmo quando uma falha. Sem a `develop` (nem a local nem `origin/develop`), ele roda como `--all`. Rode `--full` quando quiser a mesma cobertura da CI.

A CI roda tudo isso (o mesmo que o `--full`) em cada pull request e em cada push na `main`: o backend no Linux e no macOS; o frontend e o E2E no Linux.

### Testes de ponta a ponta (E2E)

Os specs ficam em `frontend/e2e/` e usam o Playwright com o Google Chrome instalado na máquina (não baixam navegador). Sem o Google Chrome, rode `pnpm --dir frontend exec playwright install chrome`. `pnpm --dir frontend e2e` sobe sozinho um backend descartável (`scripts/e2e_server.py`), com projetos e conversas de exemplo num diretório temporário: nada toca em `~/.claude`, no seu banco ou no SDK. A porta vai de 6620 a 6659, uma por worktree (calculada a partir da pasta), então execuções de worktrees diferentes não colidem; `MAESTRO_E2E_PORT` força uma (nunca a dos serviços nem a do preview). Numa mesma worktree, rode uma execução por vez. O Playwright habilita `MAESTRO_E2E_CHAT=1` no servidor descartável: conversas de agentes recebem respostas determinísticas de um cliente falso, sem iniciar processos do SDK. As conversas comuns continuam recusando o agente. O servidor manual mantém a recusa por padrão; a mesma variável habilita o cliente falso para exploração.

Para explorar uma tela à mão, rode `uv run python scripts/e2e_server.py` de dentro da worktree (ele recusa se o `uv run` servir outro checkout) e abra `http://127.0.0.1:6620`, a porta padrão do servidor manual; pare-o antes de rodar o `pnpm --dir frontend e2e`. Com o Claude Code, o agente `e2e-tester` faz isso e escreve os specs (o [Playwright CLI](https://github.com/microsoft/playwright-cli) ajuda a descobrir seletores).

O receptor opcional de comentários do GitHub usa `MAESTRO_HOOKS_PORT`, em uma porta de loopback própria. Use outra porta que a dos serviços, do preview e do E2E. Os testes substituem o `gh` e não acessam o GitHub real.

## agentd

O agentd é o processo auxiliar que mantém os processos do agente vivos quando o backend reinicia. O código fica em `backend/claudio_maestro/agentd/`, só usa a biblioteca padrão do Python, e o protocolo tem versão (`PROTOCOL`).

- Um agentd já em execução continua com o código antigo. Quem muda o agentd precisa encerrá-lo para testar (`kill $(cat <data_dir>/agentd-v1.lock)`) ou subir o `PROTOCOL`.
- As provas de fechamento das tarefas usam o nonce da instância do agentd, além da identidade persistida do processo. Um daemon substituto, socket ausente ou registro antigo sem nonce não comprovam a morte do processo original. Uma futura adoção com daemon antigo pode exigir reinício coordenado; não encerre o daemon em uso para simular essa prova.
- Envios têm UUID persistido, eco no mesmo cliente/geração e Result correlacionado. Nos testes de crash/fechamento, preserve `closing`/incerteza até uma confirmação válida: `POST /api/work-attempts/{id}/reconcile-close` concilia o fechamento sem reenviar e conserva a pausa. Não adicionar nem usar uma ação de apagar o estado à força.
- Neste trabalho, o protocolo e a recuperação foram exercitados só com clientes falsos e sockets/processos temporários. Nenhum agentd ou serviço real foi alterado ou testado; a compatibilidade na instalação em uso não foi ensaiada.
- O log fica em `<data_dir>/agentd.log`.
- O teste de contrato `backend/tests/test_agent_spawn.py` quebra quando o SDK muda a montagem do comando que inicia o agente.
- `MAESTRO_AGENTD=0` desliga o agentd; os testes automatizados já rodam assim.
- Para conferir contra o SDK real: `uv run python scripts/agentd_smoke.py` (consome a assinatura).

## Regras do projeto

- **Testes antes do código.** Escreva o teste, veja falhar, implemente, veja passar.
- **Testes automatizados nunca tocam o SDK real.** O SDK fica atrás de uma interface, e os testes usam um cliente falso (veja `backend/tests/conftest.py`).
- **Só `pnpm` no frontend.** Nunca `npx` nem `yarn`: o `npx` já criou arquivos do Yarn PnP em `frontend/` e quebrou a compilação.
- **Idiomas.** Textos da interface e documentação em português brasileiro. Código e identificadores em inglês.
- **Marca.** Não use "Claude Code" como nome na interface.
- **Segurança.** Leia a seção de segurança do [CLAUDE.md](CLAUDE.md) antes de mexer em rotas, caminhos, git ou processos: `git` só por `run_git`, caminhos sempre dentro dos projetos cadastrados, processos com argumentos em lista e sem shell.
- **Leve, não IDE.** Na dúvida entre duas soluções, a que mantém o app leve e a leitura clara. Os princípios de design estão no [PRODUCT.md](PRODUCT.md).

## Testes manuais contra o SDK real

Os scripts em `scripts/` (`sdk_smoke.py`, `agentd_smoke.py` e outros) falam com o SDK de verdade e **consomem a sua assinatura ou os seus créditos de API**. Use com moderação: poucas chamadas, prompts mínimos, modelo `haiku`, pasta temporária e `setting_sources=[]`. Dentro de uma sessão do Claude Code, remova do ambiente as variáveis que começam com `CLAUDE` antes de rodar.

## Commits

Formato: `[Tipo] Título`, em português, verbo no infinitivo, até 72 caracteres, sem ponto final. Um commit por unidade lógica.

| Tipo | Uso |
|---|---|
| `[Feat]` | Funcionalidade nova |
| `[Bugfix]` | Correção de bug |
| `[Refactor]` | Mudança sem alterar comportamento |
| `[UI]` | Mudança visual |
| `[Docs]` | Documentação |
| `[Test]` | Testes |
| `[Chore]` | Configuração, dependências, CI |
| `[Release]` | Versão pronta para lançar |

Exemplo: `[Feat] Mostrar a branch de cada worktree no menu lateral`.

## Branches

- A `develop` é a branch de integração. O trabalho parte dela e volta para ela, e é o que o mantenedor roda no dia a dia. Ela deve estar sempre pronta para lançar.
- A `main` só recebe releases. Ninguém faz commit direto nela, e ela só avança por fast-forward, a partir da `develop`.
- A branch padrão do GitHub continua sendo a `main`, para quem clona receber a versão estável.

## Pull requests

- Abra o PR contra a `develop`, não contra a `main`. O Dependabot também mira a `develop`.
- Um assunto por PR.
- Diga o que mudou e como você testou. Mudança visual pede uma captura de tela.
- CI verde antes da revisão.
- Mudanças que o usuário percebe entram no [CHANGELOG.md](CHANGELOG.md), na seção "Não lançado".

## Lançar uma versão

Para quem mantém o projeto. A versão sai da `develop`; o GitHub confere e publica.

No Claude Code, `/release` (com `patch`, `minor` ou `atual`; sem argumento, ele sugere o tipo olhando o CHANGELOG) conduz o lado local: revisa o "Não lançado" com você, carimba o CHANGELOG e o `pyproject.toml`, atualiza o `uv.lock` e, só depois do seu "ok", faz `git push --atomic origin HEAD:develop HEAD:main` do commit `[Release]`. Os dois destinos precisam ser fast-forward; ele nunca faz merge nem force push. Não espera a CI.

O push na `main` roda a CI completa. Se todos os jobs passam, o workflow `Release` (`.github/workflows/release.yml`) cria a tag anotada `vX.Y.Z` e publica a release com as notas da versão no CHANGELOG. Se a CI falhar, a `main` fica com o commit `[Release]`, mas sem tag e sem release, e o app de quem instalou não oferece atualização. A correção entra na `develop` pelo fluxo normal, e um novo `/release` percebe que a versão já está carimbada e sem tag: não carimba de novo, só envia a `develop` para a `main`.

O cálculo da versão e a troca nos arquivos ficam em `scripts/release.py` (`suggest`, `check`, `prepare`, `pending` e `notes`), que também dá para rodar à mão. O passo a passo está em `.claude/skills/release/SKILL.md`.

Os scripts de `scripts/` são ferramentas de quem mantém o projeto e chamam o `git` direto; a regra do `run_git` vale para o app, não para eles.

## Usando o Claude Code para contribuir

O [CLAUDE.md](CLAUDE.md) tem as regras do projeto, e `.claude/agents/` traz três agentes prontos: `implementer` (implementa com testes antes), `reviewer` (revisa uma tarefa) e `milestone-reviewer` (revisão profunda de um conjunto de mudanças). A seção "Agentes" do CLAUDE.md lista as áreas críticas, em que a revisão de cada tarefa roda em Opus.

## Falhas de segurança

Não abra issue pública. Veja o [SECURITY.md](SECURITY.md).
