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
- **Processos.** git, o editor e o seletor de pastas rodam com argumentos em lista, nunca por shell.
- **agentd.** O processo auxiliar que guarda os processos do agente escuta só num socket Unix com permissão 0600, numa pasta 0700, e confere o uid de quem conecta. Não abre porta de rede. Quem consegue falar com o socket já roda código como o seu usuário. O conteúdo das conversas fica só em memória, nunca em disco.
- **Tamanho.** Corpos acima de 60 MB são recusados.
- **Saída para a internet.** A única conexão que o app abre por conta própria é uma leitura da última release em `api.github.com`, um minuto depois de subir e uma vez por dia. Nenhum dado de projeto ou conversa é enviado, e as notas da versão são mostradas sem HTML. `MAESTRO_UPDATE_CHECK=0` desliga.

Fora do modelo: alguém com acesso à sua conta no sistema operacional, e expor o app na rede (não faça isso).

## Versões com suporte

Só a versão mais recente, na branch `main`.

## Como relatar uma falha

Use o [relato privado de vulnerabilidades do GitHub](https://github.com/vateiixeira/claudio-maestro/security/advisories/new). Descreva o problema, como reproduzir e o impacto que você vê. Não abra issue pública com detalhes da falha.

A resposta inicial vem em até 7 dias. Quando a correção sair, o crédito é seu, se quiser.
