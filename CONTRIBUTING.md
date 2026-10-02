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

Acesse **http://localhost:6610**. O preview usa os dados reais do backend: o que você fizer nele vale de verdade. Mudanças de backend da worktree não aparecem aqui; para elas, suba outra instância com `MAESTRO_DATA_DIR` próprio.

## Testes e verificações

```bash
uv run pytest                  # backend
uv run ruff check              # lint do backend
pnpm --dir frontend test       # frontend
pnpm --dir frontend build      # compilação e checagem de tipos
```

A CI roda tudo isso em cada pull request, no Linux e no macOS.

## agentd

O agentd é o processo auxiliar que mantém os processos do agente vivos quando o backend reinicia. O código fica em `backend/claudio_maestro/agentd/`, só usa a biblioteca padrão do Python, e o protocolo tem versão (`PROTOCOL`).

- Um agentd já em execução continua com o código antigo. Quem muda o agentd precisa encerrá-lo para testar (`kill $(cat <data_dir>/agentd-v1.lock)`) ou subir o `PROTOCOL`.
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

## Pull requests

- Um assunto por PR.
- Diga o que mudou e como você testou. Mudança visual pede uma captura de tela.
- CI verde antes da revisão.
- Mudanças que o usuário percebe entram no [CHANGELOG.md](CHANGELOG.md), na seção "Não lançado".

## Usando o Claude Code para contribuir

O [CLAUDE.md](CLAUDE.md) tem as regras do projeto, e `.claude/agents/` traz três agentes prontos: `implementer` (implementa com testes antes), `reviewer` (revisa uma tarefa) e `milestone-reviewer` (revisão profunda de um conjunto de mudanças).

## Falhas de segurança

Não abra issue pública. Veja o [SECURITY.md](SECURITY.md).
