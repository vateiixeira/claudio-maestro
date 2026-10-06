#!/usr/bin/env bash
# Roda as mesmas verificações da CI (.github/workflows/ci.yml), na raiz do repositório.
# Roda todas mesmo quando uma falha e termina com código 1 se alguma falhou.
# Não instala dependências: rode `uv sync` e `pnpm --dir frontend install` antes, se preciso.
set -u
cd "$(dirname "$0")/.."

checks=(
  "uv run ruff check"
  "uv run pytest -q"
  "pnpm --dir frontend test"
  "pnpm --dir frontend build"
)

failed=()
for check in "${checks[@]}"; do
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
