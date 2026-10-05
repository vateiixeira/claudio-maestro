---
name: release
description: Use quando o mantenedor pedir para lançar uma versão do Cláudio Maestro, ou digitar /release (com patch, minor ou atual, ou sem argumento).
argument-hint: "[patch | minor | atual]"
---

# Lançar uma versão

Para quem mantém o projeto. Fase 0.x: correção sobe o patch, funcionalidade sobe o minor.

1. **Tipo.** Aceite `patch`, `minor` ou `atual` (a versão que já está no `pyproject.toml` e não foi lançada). Recuse `major`. Sem argumento, rode `uv run python scripts/release.py suggest`, mostre a sugestão, o motivo e a última release (`gh release view --json tagName,publishedAt`) e pergunte se confirma ou prefere outro tipo.
2. **Pré-requisitos.** `gh auth status`. Depois `git fetch origin` e confira a CI do commit de `origin/main`: `gh run list --branch main --commit $(git rev-parse origin/main) --json conclusion,status`. CI vermelha, rodando ou sem nenhum run (lista vazia): pare.
3. **Worktree.** Numa chamada só de shell: `S=$(date +%Y%m%d-%H%M); git worktree add .claude/worktrees/release-$S -b chore/release-$S origin/main && echo "$S"`. Anote o caminho e a branch para os passos seguintes. A versão só aparece no commit e na tag. Dentro dela: `uv run python scripts/release.py check <tipo>`. Erro: pare e relate. Aviso com `patch`: pergunte se não é `minor`. A saída traz `version=X.Y.Z`.
4. **Revisar o "Não lançado"** antes de carimbar: junte itens repetidos ou sobrepostos e corte os que descrevem um estado intermediário depois refeito ou desfeito, mantendo só o resultado final. Não invente: cada linha revisada precisa vir de itens que já estavam lá. Mantenha subseções e ordem. Escreva um resumo de 1 ou 2 frases. Mostre o diff e espere o "ok" explícito; o mantenedor pode recusar e lançar como está.
5. **Carimbar.** `uv run python scripts/release.py prepare X.Y.Z --summary "..." --notes-out <arquivo temporário>`, depois `uv lock`.
6. **Verificar** o que a CI roda: `uv run pytest`, `uv run ruff check`, `pnpm --dir frontend install --frozen-lockfile`, `pnpm --dir frontend test`, `pnpm --dir frontend build`. Falha: pare.
7. **Aprovação.** Mostre as notas e `git diff --stat` e **espere o "ok" para publicar**.
8. **Publicar.** `git add pyproject.toml uv.lock CHANGELOG.md` e commit `[Release] Lançar a versão X.Y.Z`. Rode `git fetch origin`: se `origin/main` andou, não faça rebase (o CHANGELOG tende a conflitar); descarte a worktree e recomece do passo 3, para o diff e o "ok" mostrarem o conteúdo real. Senão, nesta ordem:
   - `git tag -a vX.Y.Z -m "Cláudio Maestro X.Y.Z"` (antes de qualquer push)
   - `git push --atomic origin HEAD:main vX.Y.Z` (nunca force push)
   - `gh release create vX.Y.Z --verify-tag --title "Cláudio Maestro X.Y.Z" --notes-file <arquivo>`

   Push recusado: nada foi publicado; apague a tag local (`git tag -d vX.Y.Z`) e investigue. Push feito mas `gh release create` falhou: não refaça commit nem tag; rode só o `gh release create` de novo, com o mesmo arquivo de notas.
9. **Conferir.** `gh release view vX.Y.Z` e acompanhe a CI da `main`: `gh run list --branch main --limit 3`, `gh run watch <id>`.
10. **Depois.** Se existir `CLAUDE.local.md` na raiz, siga os passos de depois de publicar descritos lá (pull, reinício de serviços). A partir do checkout principal, remova a worktree e a branch: `git worktree remove <caminho>` e `git branch -D <branch>`.

## Erros comuns

- Lançar com a CI vermelha, rodando ou sem run.
- Esquecer o `uv.lock` (rode `uv lock`).
- Force push na `main`; se o push for recusado, investigue.
- Inventar itens no CHANGELOG: a revisão só reorganiza o que já estava escrito.
