---
name: release
description: Use quando o mantenedor pedir para lançar uma versão do Cláudio Maestro, ou digitar /release (com patch, minor ou atual, ou sem argumento).
argument-hint: "[patch | minor | atual]"
---

# Lançar uma versão

Para quem mantém o projeto. Fase 0.x: correção sobe o patch, funcionalidade sobe o minor.

O trabalho do dia a dia vive na `develop`. O `/release` carimba a versão na `develop` e faz push do mesmo commit na `develop` e na `main` (fast-forward). Quem roda a CI completa, cria a tag `vX.Y.Z` e publica a release é o GitHub, e só se a CI passar. O `/release` não espera a CI e não cria tag nem release.

1. **Tipo.** Aceite `patch`, `minor` ou `atual` (a versão que já está no `pyproject.toml` e não foi lançada). Recuse `major`. Sem argumento, rode `uv run python scripts/release.py suggest`, mostre a sugestão, o motivo e a última release (`gh release view --json tagName,publishedAt`) e pergunte se confirma ou prefere outro tipo.
2. **Pré-requisitos.** `gh auth status` e `git fetch origin`. Não confira a CI antes: ela roda depois do push, na `main`.
3. **Versão já carimbada?** Mostre `git log --oneline origin/main..origin/develop` (o que vai entrar) e rode `uv run python scripts/release.py pending` no checkout principal, depois de um `git pull --ff-only` na `develop`. Se a saída for `pending=X.Y.Z`, uma release anterior chegou à `main` e a CI a barrou: a versão está carimbada e sem tag. Não carimbe de novo e não crie worktree de carimbo. Antes de reenviar, confira o último run da `main`: `gh run list --branch main --limit 1 --json status,conclusion,headSha`. Se ele ainda está rodando, ou se `origin/main..origin/develop` está vazio, não há o que subir: mostre o run e pare. Se o `git pull --ff-only` falhar no checkout principal, pare e relate. Do contrário, mostre o que vai subir (o log acima, que inclui as correções feitas depois), espere o "ok" e vá direto ao push do passo 7, com `git push origin origin/develop:main` (fast-forward), seguido do passo 8. Se for `pending=` (vazio), espere o "ok" sobre o log e siga para o passo 4.
4. **Worktree.** Numa chamada só de shell: `S=$(date +%Y%m%d-%H%M); git worktree add .claude/worktrees/release-$S -b chore/release-$S origin/develop && echo "$S"`. Anote o caminho e a branch para os passos seguintes. Dentro dela: `uv run python scripts/release.py check <tipo>`. Ele exige `HEAD` igual à `origin/develop` e a `origin/main` como ancestral dela. Erro: pare e relate. Se a `main` não for ancestral da `develop`, ela andou por fora: não faça merge, investigue. Aviso com `patch`: pergunte se não é `minor`. A saída traz `version=X.Y.Z`.
5. **Revisar o "Não lançado"** antes de carimbar: junte itens repetidos ou sobrepostos e corte os que descrevem um estado intermediário depois refeito ou desfeito, mantendo só o resultado final. Não invente: cada linha revisada precisa vir de itens que já estavam lá. Mantenha subseções e ordem. Escreva um resumo de 1 ou 2 frases. Mostre o diff e espere o "ok" explícito; o mantenedor pode recusar e lançar como está.
6. **Carimbar.** `uv run python scripts/release.py prepare X.Y.Z --summary "..." --notes-out <arquivo temporário>`, depois `uv lock`. Não rode as verificações aqui: quem verifica é a CI da `main`, antes de sair a tag.
7. **Aprovação e push.** `git add pyproject.toml uv.lock CHANGELOG.md` e commit `[Release] Lançar a versão X.Y.Z`. Mostre as notas e `git diff --stat` e **espere o "ok para publicar"**. Depois:

   ```bash
   git push --atomic origin HEAD:develop HEAD:main
   ```

   Nunca force push. As duas atualizações precisam ser fast-forward.

   Push recusado: nada foi publicado; investigue antes de qualquer outra coisa. Se foi a `develop` que andou (alguém integrou nela depois do passo 4), descarte a worktree e recomece do passo 4, para o diff e o "ok" mostrarem o conteúdo real; não faça rebase (o CHANGELOG tende a conflitar). Se foi a `main` que recusou, ela tem algo que a `develop` não tem: pare e investigue, sem merge nem force push.
8. **Acompanhar.** Mostre o link do run da CI na `main`, pegando o run do commit enviado: `gh run list --branch main --commit <sha> --limit 1 --json url`. Se o run ainda não apareceu, diga que ele aparece em instantes e mostre o link da lista de Actions do repositório. Termine aí, sem esperar. Se a CI passar, o workflow `Release` cria a tag e a release sozinho. Se ela falhar, não sai tag nem release; a correção entra na `develop` e um novo `/release` reenvia a versão sem carimbar de novo (passo 3). Se a tag existe e a release não (o workflow falhou no meio), basta reexecutar o workflow `Release` (`gh run rerun <id>`), sem criar nada à mão.
9. **Depois.** Se existir `CLAUDE.local.md` na raiz, siga os passos de depois de publicar descritos lá (pull na `develop`, reinício de serviços). A partir do checkout principal, remova a worktree e a branch: `git worktree remove <caminho>` e `git branch -D <branch>`.

## Erros comuns

- Esquecer o `uv.lock` (rode `uv lock`).
- Fazer merge ou force push na `main`; se o push for recusado, investigue.
- Criar tag ou release à mão: isso é do workflow `Release`, depois da CI verde.
- Carimbar de novo uma versão que já está carimbada e sem tag (use o passo 3).
- Inventar itens no CHANGELOG: a revisão só reorganiza o que já estava escrito.
