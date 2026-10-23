#!/usr/bin/env bash
# Roda na raiz do repositório as verificações que a mudança pede, comparando com a develop.
# Uso: scripts/check.sh [--e2e] [--all] [--full] [--dry-run]
#   (sem opção)  escolhe pelo diff contra a develop (commitado ou não, mais arquivos novos):
#                backend/, pyproject.toml, uv.lock, scripts/  -> ruff e pytest
#                frontend/                                    -> vitest e build
#                .github/, scripts/check.sh                   -> os quatro
#   --e2e        acrescenta o E2E ao que foi escolhido
#   --all        os quatro, sem E2E
#   --full       os cinco, as mesmas verificações da CI (.github/workflows/ci.yml)
#   --dry-run    só imprime o que rodaria
# Roda tudo o que foi escolhido mesmo quando uma falha e termina com código 1 se alguma falhou.
# Não instala dependências: rode `uv sync` e `pnpm --dir frontend install` antes, se preciso.
set -u
cd "$(dirname "$0")/.."

# Ordem importa: 0 e 1 são do backend, 2 e 3 do frontend, 4 é o E2E.
checks=(
  "uv run ruff check"
  "uv run pytest -q"
  "pnpm --dir frontend test"
  "pnpm --dir frontend build"
  "pnpm --dir frontend e2e"
)

usage() {
  echo "Uso: scripts/check.sh [--e2e] [--all] [--full] [--dry-run]" >&2
}

want_e2e=0 all=0 full=0 dry_run=0
for arg in "$@"; do
  case "$arg" in
    --e2e) want_e2e=1 ;;
    --all) all=1 ;;
    --full) full=1 ;;
    --dry-run) dry_run=1 ;;
    *) echo "Opção desconhecida: $arg" >&2; usage; exit 2 ;;
  esac
done

selected=(0 0 0 0 0)

if [ "$full" -eq 1 ]; then
  selected=(1 1 1 1 1)
elif [ "$all" -eq 1 ]; then
  selected=(1 1 1 1 0)
else
  base=""
  if git rev-parse --verify -q refs/remotes/origin/develop >/dev/null; then
    base="origin/develop"
  elif git rev-parse --verify -q refs/heads/develop >/dev/null; then
    base="develop"
  fi
  merge_base=""
  [ -n "$base" ] && merge_base=$(git merge-base HEAD "$base" 2>/dev/null || true)
  if [ -z "$merge_base" ]; then
    echo "sem develop para comparar; rodando tudo, menos E2E"
    selected=(1 1 1 1 0)
  else
    # -z: nomes separados por NUL e sem aspas/octal; --no-renames lista origem e destino de um mv.
    while IFS= read -r -d '' file; do
      [ -z "$file" ] && continue
      case "$file" in
        scripts/check.sh | .github/*) selected=(1 1 1 1 0) ;;
        backend/* | pyproject.toml | uv.lock | scripts/*) selected[0]=1; selected[1]=1 ;;
        frontend/*) selected[2]=1; selected[3]=1 ;;
      esac
    done < <({ git diff --name-only -z --no-renames "$merge_base"; git ls-files -z --others --exclude-standard; })
  fi
fi

[ "$want_e2e" -eq 1 ] && selected[4]=1

to_run=()
for i in "${!checks[@]}"; do
  [ "${selected[$i]}" -eq 1 ] && to_run+=("${checks[$i]}")
done

if [ ${#to_run[@]} -eq 0 ]; then
  echo "Nada para verificar: a mudança não toca backend nem frontend."
  exit 0
fi

if [ "$dry_run" -eq 1 ]; then
  for check in "${to_run[@]}"; do
    echo "==> $check"
  done
  exit 0
fi

failed=()
for check in "${to_run[@]}"; do
  echo "==> $check"
  if ! bash -c "$check"; then
    failed+=("$check")
  fi
done

echo
if [ ${#failed[@]} -eq 0 ]; then
  echo "Tudo passou."
  exit 0
fi
echo "Falhou:"
printf '  %s\n' "${failed[@]}"
exit 1
