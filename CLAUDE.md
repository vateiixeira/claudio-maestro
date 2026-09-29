# Vini7 Vibing

App web local que substitui a extensão do VSCode e o CLI do Claude Code no uso diário do Vinicius. Roda na máquina dele, abre no navegador e controla sessões do Claude Code pelo Claude Agent SDK em Python. Usuário único.

Resolve dois problemas: a extensão do VSCode é pesada e ruim para multiprojeto, e o terminal dificulta ler diffs, saídas e estados. Na dúvida entre duas soluções, prefira a que mantém o app leve e a leitura clara. O app não deve virar um IDE.

## Documentos

| Arquivo | Para que serve |
|---|---|
| `ROADMAP.md` | Progresso da construção. Fonte única do que está feito e do que falta |
| `docs/prompts/2026-09-28-construir-mvp.md` | Requisitos completos, identidade visual e fatos verificados do SDK |
| `docs/superpowers/specs/2026-09-28-vini7-vibing-design.md` | Detalhamento de dados, estados, rotas e erros |
| `docs/design/project/*.dc.html` | Telas aprovadas (cópia local do artefato https://claude.ai/artifact/JAVD4f5uhJMr5WZodBe97A) |

Em caso de divergência, a ordem é: este arquivo, depois o prompt, depois a spec. As portas e a forma de execução descritas aqui substituem as da seção 16 da spec.

## Manter o roadmap em dia

Ao começar um marco do `ROADMAP.md`, troque o estado dele para "Em andamento". Ao terminar um item, marque com `[x]` e a data, e atualize a contagem na tabela. Só marque depois de rodar os testes e vê-los passar. Se descobrir trabalho que não estava previsto, acrescente como item novo em vez de fazer sem registrar.

## Stack

- Monolito: `backend/` e `frontend/` no mesmo repositório, `pyproject.toml` na raiz.
- Backend: Python 3.13, FastAPI, uv, SQLite, `claude-agent-sdk` 0.2.161 ou superior, pytest.
- Frontend: Vue 3, Vite, TypeScript, Pinia, Vue Router, Tailwind CSS, Vitest, pnpm.

## Execução

Roda direto na máquina, sem Docker, em modo de desenvolvimento. Os dois processos recarregam sozinhos quando o código muda.

| Processo | Roda | Endereço |
|---|---|---|
| Backend | uvicorn com `--reload` | `127.0.0.1:6660` |
| Frontend | servidor de desenvolvimento do Vite | `127.0.0.1:6600`, com proxy de `/api` e `/ws` para o backend |

O app é acessado em `http://localhost:6600`.

As portas ficam acima de 1024 porque o Linux reserva as menores ao root. Não use 6665 a 6669: os navegadores bloqueiam.

Docker foi adiado. Se voltar à pauta, o processo `claude` passa a rodar dentro do container, o que exige montar `~/.claude`, `~/.claude.json` e a pasta dos projetos no mesmo caminho absoluto do host, e limita o Claude às ferramentas instaladas na imagem. Nada disso foi testado.

### Comandos

Rode a partir da raiz do repositório. Na primeira vez: `uv sync` e `pnpm --dir frontend install`.

```bash
uv run uvicorn vibing.app:app --reload --reload-dir backend --host 127.0.0.1 --port 6660   # backend
pnpm --dir frontend dev                                                                    # frontend
uv run pytest                                                                              # testes do backend
pnpm --dir frontend test                                                                   # testes do frontend
pnpm --dir frontend build                                                                  # compilação do frontend
uv run python scripts/sdk_smoke.py                                                         # teste manual contra o SDK real (consome a assinatura)
```

## Regras

- Commits por tarefa estão autorizados neste projeto. Esta regra vale sobre a regra global do usuário de só commitar a pedido.
- Faça um commit ao concluir cada item do roadmap, depois de ver os testes passarem. Um commit por unidade lógica, sem misturar tipos.
- Mensagens no formato do usuário: `[Tipo] Título` em português, verbo no infinitivo, até 72 caracteres, sem ponto final. Tipos: Feat, Bugfix, Refactor, UI, Docs, Test, Chore.
- Não faça push nem crie repositório remoto sem o usuário pedir.
- Escreva os testes antes do código que eles cobrem.
- Textos da interface e documentação em português brasileiro. Código e identificadores em inglês.
- Não use a marca "Claude Code" na interface.
- Use o login de assinatura existente. Não configure nem peça `ANTHROPIC_API_KEY`.
- As conversas ficam em `~/.claude/projects`. O SQLite guarda só metadados.
- Ao relatar, separe o que você rodou e viu passar do que só escreveu.

## Subagentes

- Ao usar subagentes para implementar (por exemplo, depois de brainstorming ou plano), o padrão é o modelo Opus 5.5 com raciocínio baixo (low).
- Antes de disparar, pergunte ao usuário se pode. Ele responde se usa esse padrão, o modelo atual da sessão ou outro.
- O agente `implementer` (`.claude/agents/implementer.md`) já vem com Opus e raciocínio baixo. Para usar o modelo da sessão ou outro, passe `model` ao chamá-lo.
- Subagentes não fazem commit nem `git add`. Quem commita é a sessão principal, depois de conferir o trabalho e ver os testes passarem.

### Revisão de código em duas camadas

| Quando | Agente | Modelo |
|---|---|---|
| Depois de cada tarefa | `reviewer` | Sonnet 5, raciocínio médio |
| No fim de cada marco | `milestone-reviewer` | Opus 5.5, raciocínio alto |

Uma tarefa só é commitada depois de o `reviewer` aprovar. Um marco só é dado como concluído depois de o `milestone-reviewer` aprovar. Quando um revisor reprova, o `implementer` corrige e o mesmo revisor olha de novo.

## Segurança

O app executa comandos na máquina, então qualquer site aberto no navegador é uma ameaça a um servidor local.

- Escute só em 127.0.0.1.
- Recuse requisições cujo `Host` não seja `localhost` ou `127.0.0.1` nas portas 6600 e 6660.
- Recuse WebSockets e requisições que alteram estado cuja origem não seja a do próprio app.
- Não libere CORS.
- Toda requisição a `/api/` precisa do cabeçalho `X-Vibing: 1`, que o cliente do frontend envia. Isso impede outros sites de dispararem leituras por `<img>`, formulário ou `fetch`.
- Todo `git` passa por `run_git` em `backend/vibing/gitinfo.py`, que neutraliza fsmonitor, pager, hooks, diff externo, textconv, filtros e submódulos. Não chame `git` por outro caminho.
- Todo caminho recebido precisa estar, depois de resolvido, dentro da pasta de um projeto registrado.
- Execute git e o editor com argumentos em lista, sem shell.

## Testes contra o SDK real

Os testes automatizados nunca tocam o SDK real. Ele fica atrás de uma interface, e os testes usam um cliente falso.

Testes manuais contra o SDK real consomem a assinatura do usuário:

- Poucas chamadas, prompts mínimos, modelo `haiku`.
- Pasta temporária e `setting_sources=[]`, para não disparar hooks e plugins.
- Apague as sessões de teste com `delete_session` ao terminar.
- Dentro de uma sessão do Claude Code, remova do ambiente as variáveis que começam com `CLAUDE` antes de iniciar o SDK.
