# Segurança

## Modelo de ameaça

O Cláudio Maestro executa comandos na sua máquina por meio do Claude. Ele é um servidor HTTP local, e qualquer site aberto no seu navegador consegue mandar requisições para `localhost`. Por isso o app trata o navegador como território hostil.

Defesas:

- **Só local.** O servidor escuta apenas em `127.0.0.1`, sem opção de mudar.
- **`Host`.** Requisições com `Host` diferente de `localhost` ou `127.0.0.1` nas portas do app são recusadas (bloqueia DNS rebinding).
- **`Origin`.** WebSockets e requisições que alteram estado precisam vir da origem do próprio app.
- **Sem CORS.** Nenhuma origem externa é liberada.
- **Cabeçalho próprio.** Toda chamada a `/api/` exige `X-Maestro: 1`. Navegadores só enviam cabeçalhos próprios entre sites depois de uma checagem de CORS, que o app recusa, então outros sites não conseguem ler a API por `<img>`, formulário ou `fetch`.
- **Caminhos.** Todo caminho recebido é resolvido, seguindo links simbólicos, e precisa estar dentro da pasta de um projeto cadastrado. A única exceção é uma worktree git comprovadamente ligada a um repositório de um projeto.
- **git.** Toda chamada passa por `run_git`, que neutraliza fsmonitor, pager, hooks, diff externo, textconv, filtros e submódulos.
- **Processos.** git, o editor e o seletor de pastas rodam com argumentos em lista, nunca por shell.
- **Tamanho.** Corpos acima de 60 MB são recusados.

Fora do modelo: alguém com acesso à sua conta no sistema operacional, e expor o app na rede (não faça isso).

## Versões com suporte

Só a versão mais recente, na branch `main`.

## Como relatar uma falha

Use o [relato privado de vulnerabilidades do GitHub](https://github.com/vateiixeira/claudio-maestro/security/advisories/new). Descreva o problema, como reproduzir e o impacto que você vê. Não abra issue pública com detalhes da falha.

A resposta inicial vem em até 7 dias. Quando a correção sair, o crédito é seu, se quiser.
