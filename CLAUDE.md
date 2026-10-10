# Cláudio Maestro

App web local que reúne numa tela só as sessões do Claude em vários projetos. Roda na máquina de quem usa, abre no navegador e controla as sessões pelo Claude Agent SDK em Python. Uma pessoa por instalação, sem acesso pela rede.

Resolve dois problemas: a extensão do VSCode é pesada e ruim para multiprojeto, e o terminal dificulta ler diffs, saídas e estados. Na dúvida entre duas soluções, prefira a que mantém o app leve e a leitura clara. O app não deve virar um IDE.

## Documentos

| Arquivo | Para que serve |
|---|---|
| `README.md` | O que é, instalação, configuração |
| `CONTRIBUTING.md` | Ambiente de desenvolvimento, regras, commits e PRs |
| `SECURITY.md` | Modelo de ameaça e como relatar falhas |
| `PRODUCT.md` | Para quem é, princípios de design e identidade visual |
| `ROADMAP.md` | O que pode vir a seguir |
| `CHANGELOG.md` | O que mudou em cada versão |

## Stack

- Monolito: `backend/` e `frontend/` no mesmo repositório, `pyproject.toml` na raiz.
- Backend: Python 3.13, FastAPI, uv, SQLite, `claude-agent-sdk` 0.2.161 ou superior, pytest, ruff. Código em `backend/claudio_maestro/`.
- Frontend: Vue 3, Vite, TypeScript, Pinia, Vue Router, Tailwind CSS, Vitest, pnpm.

## Execução

| Modo | Comando | Endereço |
|---|---|---|
| Uso | `uv run claudio-maestro` (compila o frontend quando preciso e serve tudo) | `http://localhost:6660` |
| Desenvolvimento, backend | uvicorn com `--reload` | `127.0.0.1:6660` |
| Desenvolvimento, frontend | Vite, com proxy de `/api` e `/ws` para o backend | `http://localhost:6600` |

Portas: `MAESTRO_PORT` (backend e modo de uso), `MAESTRO_DEV_PORT` (Vite) e `MAESTRO_PREVIEW_PORT` (Vite de uma worktree, desligada por padrão; veja o `CONTRIBUTING.md`). Ficam entre 1024 e 65535; não use 6665 a 6669, que os navegadores bloqueiam.

### Comandos

Rode a partir da raiz do repositório. Na primeira vez: `uv sync` e `pnpm --dir frontend install`.

```bash
uv run claudio-maestro                                                                              # app completo
uv run uvicorn claudio_maestro.app:app --reload --reload-dir backend --host 127.0.0.1 --port 6660   # backend (desenvolvimento)
pnpm --dir frontend dev                                                                             # frontend (desenvolvimento)
uv run pytest                                                                                       # testes do backend
uv run ruff check                                                                                   # lint do backend
pnpm --dir frontend test                                                                            # testes do frontend
pnpm --dir frontend build                                                                           # compilação do frontend
pnpm --dir frontend e2e                                                                             # testes E2E no navegador (Playwright, Chrome do sistema, backend isolado na porta 6620 a 6659, uma por worktree; `MAESTRO_E2E_PORT` força)
scripts/check.sh                                                                                    # tudo o que a CI roda: lint, testes, compilação e E2E
uv run python scripts/sdk_smoke.py                                                                  # teste manual contra o SDK real (consome assinatura ou créditos)
```

## Regras

- Escreva os testes antes do código que eles cobrem. Fluxo novo de tela ganha também um spec em `frontend/e2e/`.
- No frontend use só `pnpm` (`pnpm --dir frontend test`, `pnpm --dir frontend exec vitest ...`). Nunca `npx` nem `yarn`: o `npx` já criou arquivos do Yarn PnP em `frontend/` e quebrou a compilação.
- Textos da interface e documentação em português brasileiro. Código e identificadores em inglês.
- Não use a marca "Claude Code" na interface.
- As conversas ficam em `~/.claude/projects`, compatíveis com o CLI. O SQLite guarda só metadados.
- Commits: `[Tipo] Título` em português, verbo no infinitivo, até 72 caracteres, sem ponto final. Tipos: Feat, Bugfix, Refactor, UI, Docs, Test, Chore, Release. Um commit por unidade lógica.
- Mudanças que o usuário percebe entram no `CHANGELOG.md`, em "Não lançado".
- Ao relatar, separe o que você rodou e viu passar do que só escreveu.

## Segurança

O app executa comandos na máquina, então qualquer site aberto no navegador é uma ameaça a um servidor local.

- Escute só em 127.0.0.1.
- Recuse requisições cujo `Host` não seja `localhost` ou `127.0.0.1` nas portas do app.
- Recuse WebSockets e requisições que alteram estado cuja origem não seja a do próprio app.
- Não libere CORS.
- Toda requisição a `/api/` precisa do cabeçalho `X-Maestro: 1`, que o cliente do frontend envia. Isso impede outros sites de dispararem leituras por `<img>`, formulário ou `fetch`.
- Todo `git` passa por `run_git` em `backend/claudio_maestro/gitinfo.py`, que neutraliza fsmonitor, pager, hooks, diff externo, textconv, filtros e submódulos. Não chame `git` por outro caminho.
- Todo caminho recebido precisa estar, depois de resolvido, dentro da pasta de um projeto registrado. A única exceção é uma worktree git ligada a um repositório que está dentro de um projeto, comprovada pelo ponteiro `.git` de ida e volta (com `realpath`) e pela saída de `git worktree list` desse repositório.
- Execute git, o `claude`, o editor e o seletor de pastas com argumentos em lista, sem shell.

## Testes contra o SDK real

Os testes automatizados nunca tocam o SDK real. Ele fica atrás de uma interface, e os testes usam um cliente falso.

Testes manuais contra o SDK real consomem a assinatura ou os créditos de quem roda:

- Poucas chamadas, prompts mínimos, modelo `haiku`.
- Pasta temporária e `setting_sources=[]`, para não disparar hooks e plugins.
- Apague as sessões de teste com `delete_session` ao terminar.
- Dentro de uma sessão do Claude Code, remova do ambiente as variáveis que começam com `CLAUDE` antes de iniciar o SDK.

## Agentes

`.claude/agents/` tem quatro agentes para quem contribui com o Claude Code: `implementer` (implementa com testes antes), `reviewer` (revisa uma tarefa), `milestone-reviewer` (revisão profunda de um conjunto de mudanças) e `e2e-tester` (testa o frontend no navegador, escreve os specs de `frontend/e2e/` e devolve APROVADO ou REPROVADO). Subagentes não fazem commit.

Os revisores não alteram o repositório: não têm `Edit`, e o `Write` fica para reproduções no scratchpad. O `reviewer` roda em Sonnet; quando a tarefa toca uma área crítica, chame-o com `model: "opus"`. Áreas críticas:

- `security.py` (Host, Origin, validação de caminhos) e todo código que recebe caminhos ou chama `resolve_within`/`is_within` (hoje `fs.py`, `filesearch.py`, `history.py`, `projects.py`, `api/fs.py`, `api/git.py`, `api/plans.py` e `api/editor.py`).
- Todo código que inicia processos: `gitinfo.py` (o `run_git`), `gitfetch.py`, `worktree.py`, `picker.py`, `claudecli.py`, `api/claude_cli.py`, `api/editor.py`, `cli.py`, `scripts/e2e_server.py` (garante que o E2E não toque nos dados reais), `agent/` e `agentd/` (inclusive o socket e o ciclo de vida das sessões).
- `usage.py` e qualquer código que leia credenciais do CLI.
- Migrações em `db.py` e tudo que escreve em `~/.claude/projects`.
