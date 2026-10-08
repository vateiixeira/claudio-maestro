# Segurança

## Modelo de ameaça

O Cláudio Maestro executa comandos na sua máquina por meio do Claude. Ele é um servidor HTTP local, e qualquer site aberto no seu navegador consegue mandar requisições para `localhost`. Por isso o app trata o navegador como território hostil.

Defesas:

- **Só local.** O servidor escuta apenas em `127.0.0.1`, sem opção de mudar.
- **`Host`.** Requisições com `Host` diferente de `localhost` ou `127.0.0.1` nas portas do app são recusadas (bloqueia DNS rebinding). As portas do app são a do backend, a do Vite e, só quando `MAESTRO_PREVIEW_PORT` está definida, a do preview.
- **`Origin`.** WebSockets e requisições que alteram estado precisam vir da origem do próprio app.
- **Sem CORS.** Nenhuma origem externa é liberada.
- **Cabeçalho próprio.** Toda chamada a `/api/` exige `X-Maestro: 1`. Navegadores só enviam cabeçalhos próprios entre sites depois de uma checagem de CORS, que o app recusa, então outros sites não conseguem ler a API por `<img>`, formulário ou `fetch`.
- **Caminhos.** Todo caminho recebido é resolvido, seguindo links simbólicos, e precisa estar dentro da pasta de um projeto cadastrado. A única exceção é uma worktree git comprovadamente ligada a um repositório de um projeto.
- **git.** Toda chamada passa por `run_git`, que neutraliza fsmonitor, pager, hooks, diff externo, textconv, filtros e submódulos.
- **Fetch.** Para avisar sobre commits a baixar, o app roda `git fetch` só da branch remota da branch atual, pelo `run_git`, e nunca lê a configuração do repositório para isso. Do repositório ele lê apenas o upstream, a URL do remoto (só `https` ou `ssh`) e o diretório e o formato dos objetos. O fetch roda num repositório temporário limpo que compartilha o diretório de objetos, com a URL explícita e só a sua configuração global e de sistema; depois o app move o ref de rastreio com `update-ref` em compare-and-swap. Assim, chaves do repositório como `http.<url>.cookieFile`, `core.sshCommand`, `core.alternateRefsCommand`, `remote.<n>.uploadpack`, credential helpers e `insteadOf` não têm efeito. Por cima disso ficam as defesas que já valem para todo git (`GIT_ALLOW_PROTOCOL=https:ssh`, ssh com `BatchMode`, sem pedir senha, `--upload-pack` fixo, sem tags, submódulos nem manutenção) e um grupo de processos próprio, encerrado inteiro (git e ssh) no tempo limite. Repositórios rasos, clones parciais e remotos locais, `git://` ou `http://` não são verificados, e o motivo aparece no painel. Um repositório hostil ainda pode apontar para um servidor https ou ssh de terceiros; aí suas chaves ssh e seus helpers valem para esse host, o que é exposição de rede, sem execução de programa, sem pedir senha e sem escrita de arquivos. O `objects/info/alternates` do repositório ainda é consultado, só para ler objetos, sem mandar conteúdo de arquivo para a rede.
- **Processos.** git, o editor, o seletor de pastas, `uv`, `pnpm`, `systemctl`, `launchctl` e `loginctl` rodam com argumentos em lista, nunca por shell.
- **agentd.** O processo auxiliar que guarda os processos do agente escuta só num socket Unix com permissão 0600, numa pasta 0700, e confere o uid de quem conecta. Não abre porta de rede. Quem consegue falar com o socket já roda código como o seu usuário. O conteúdo das conversas fica só em memória, nunca em disco.
- **Tamanho.** Corpos acima de 60 MB são recusados.
- **Saída para a internet.** O app abre duas conexões por conta própria. Uma lê a última release em `api.github.com`, um minuto depois de subir e uma vez por dia; `MAESTRO_UPDATE_CHECK=0` desliga. A outra lê o consumo da assinatura em `api.anthropic.com/api/oauth/usage`, a cada 3 minutos e logo depois de cada turno (no máximo uma vez por minuto), com o token de login que o CLI guarda em `~/.claude/.credentials.json`; `MAESTRO_USAGE_CHECK=0` desliga. O token é lido a cada consulta e só vai para a Anthropic: não fica em memória, no banco, nos logs nem no navegador, e o app nunca o renova nem grava nesse arquivo. Nenhum dado de projeto ou conversa é enviado, e as notas da versão são mostradas sem HTML.

O botão de atualização executa `git`, `uv` e `pnpm` só no clone onde o próprio app está, só para a versão que o app anunciou depois de consultar o GitHub, e só a pedido de quem usa (requisição `POST` protegida pelas mesmas regras de `Host`, `Origin` e `X-Maestro`). O `git` passa por `run_git`, sem pedir senha (`GIT_TERMINAL_PROMPT=0`, ssh em `BatchMode`); `uv sync --frozen` e `pnpm install --frozen-lockfile` instalam o que está travado nos lockfiles da versão. Isso significa baixar e rodar código da versão nova (a compilação do frontend e o build do pacote Python pelo uv), e só a partir de um remoto que casa com o repositório oficial no GitHub. O comando `service install` grava só em `~/.config/systemd/user` (Linux) ou `~/Library/LaunchAgents` (macOS, onde também cria o log em `~/Library/Logs`) e chama `systemctl`, `launchctl` e `loginctl` com argumentos em lista.

O app inicia o `claude` instalado no sistema (o primeiro no `PATH` do processo) quando ele é pelo menos tão novo quanto o CLI embutido no SDK; senão, usa o embutido. Para descobrir a versão, roda `claude --version` ao subir e a cada 10 minutos. O botão **Atualizar o Claude**, no menu de modelos, roda `claude update` só a pedido de quem usa (requisição `POST` protegida pelas mesmas regras de `Host`, `Origin` e `X-Maestro`), com argumentos em lista, sem shell e com limite de 3 minutos. O `claude update` baixa a versão nova da Anthropic. `MAESTRO_CLAUDE_CLI=bundled` faz o app usar sempre o embutido.

Fora do modelo: alguém com acesso à sua conta no sistema operacional, e expor o app na rede (não faça isso).

## Versões com suporte

Só a versão mais recente, na branch `main`.

## Como relatar uma falha

Use o [relato privado de vulnerabilidades do GitHub](https://github.com/vateiixeira/claudio-maestro/security/advisories/new). Descreva o problema, como reproduzir e o impacto que você vê. Não abra issue pública com detalhes da falha.

A resposta inicial vem em até 7 dias. Quando a correção sair, o crédito é seu, se quiser.
