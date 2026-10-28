<p align="center">
  <img src=".github/imagens/conversa.png" alt="Cláudio Maestro com uma conversa aberta mostrando o diff de uma edição" width="900">
</p>

# Cláudio Maestro

**Um só regendo todos os seus projetos.**

O Cláudio Maestro é um app web local para entregar objetivos ao CTO de cada projeto, acompanhar tarefas e conduzir várias sessões do Claude numa tela só. Ele roda na sua máquina, abre no navegador e conversa com o Claude pelo [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview) em Python.

Nasceu de dois incômodos: a extensão do VSCode é pesada e presa a um projeto por vez, e no terminal fica difícil ler diffs, saídas de comando e saber qual sessão está esperando por você.

## Sim, isto está em português

Não, não foi engano do tradutor. O Cláudio é brasileiro: a interface é em português, a documentação também, e assim vai continuar. Aqui se escreve "commitar" sem culpa, se toma um cafezinho enquanto o agente roda os testes e se considera deploy na sexta-feira uma falta de amor-próprio.

Se você não lê português, o tradutor do navegador dá conta, e o próprio Claude também. Pull requests de quem chegou pelo tradutor são muito bem-vindos.

## O que ele faz

- **Objetivos e tarefas.** Início reúne o que precisa de você e o trabalho em andamento; Tarefas mostra responsáveis, tentativas, evidências e próximos passos. O CTO mantém uma conversa por projeto.
- **Revisão e decisões.** Entregas passam por uma revisão independente; perguntas humanas ficam ligadas à tarefa e à ação exatas. Uma investigação completa também pode ser uma entrega válida.
- **Todos os projetos numa tela.** Menu lateral com cada projeto, suas branches e suas conversas.
- **Busca no conteúdo.** A busca (Ctrl K) também procura no texto das conversas e abre na mensagem achada.
- **Estado de relance.** Cada conversa está rodando, esperando você ou finalizada, com ícone próprio além da cor. O que pede a sua atenção aparece primeiro.
- **Leitura confortável.** Respostas em markdown, o diff de cada edição, comandos com a saída, tabelas e blocos de código legíveis.
- **Você decide pela interface.** Permissões (permitir uma vez, sempre ou negar), perguntas do Claude e aprovação de planos. O pedido para editar mostra o diff, e "Permitir sempre" diz a regra que vai ser gravada.
- **Triagem pelo teclado.** Na Inbox, `j`/`k` movem, `Enter` abre, `a` permite e `d` nega, sem abrir cada conversa.
- **Notificações do sistema.** O navegador avisa quando uma conversa pede permissão, faz uma pergunta ou traz um plano (ligue em Preferências → Notificações).
- **Git sem sair do app.** Na tela do projeto, o painel de controle de versão do VS Code para todos os repositórios de uma vez: preparar, commitar, descartar, trocar e criar branch, mesclar (com o conflito à vista e o Claude para resolver), baixar, enviar e publicar. Ao lado, o histórico de commits no estilo do GitLens. A branch de cada repositório, inclusive worktrees, aparece no menu lateral, e o app busca a branch remota a cada 5 minutos.
- **Terminal da sessão.** Uma aba Terminal no painel da conversa abre um shell na pasta da sessão. O play nos comandos sugeridos roda o comando ali e manda a saída ao Claude, e dá para anexar trechos do terminal à mensagem.
- **Continuidade com o CLI.** As conversas ficam em `~/.claude/projects`, como no CLI e na extensão. Dá para retomar no Maestro uma conversa começada no terminal, e vice-versa.
- **Controles por conversa.** Modelo, nível de raciocínio, modo de permissão, imagens coladas, comandos `/` e menções `@`.
- **Resumo das conversas.** Um agente do próprio app pode resumir em fases o que cada conversa em andamento já fez.
- **Resumo ao voltar.** Ao reabrir uma conversa depois de um tempo, um card mostra o que aconteceu enquanto você estava fora e o que falta.
- **Agentes.** Rotinas com skill, memória e horários próprios, que rodam sozinhas e deixam avisos na Inbox. O merge sempre pede o seu ok (veja [Agentes](#agentes)).
- **Temas.** Maestro (o padrão), Dracula e os filtros do Monokai, escolhidos em Preferências → Geral → Tema, com uma prévia de uma sessão aberta. Veja os [Créditos](#créditos).

O que ele não é, de propósito: IDE, editor de código, terminal geral ou árvore de arquivos.

<p align="center">
  <img src=".github/imagens/visao-geral.png" alt="Visão geral com os projetos e as conversas que esperam por você" width="900">
</p>

## Começar pelo trabalho

1. Cadastre a pasta do projeto. Em **Início**, escolha esse projeto, descreva o objetivo e use **Entregar ao CTO**.
2. A conversa do **CTO** concentra os objetivos e as decisões daquele projeto. Ao trocar de projeto, você abre a conversa correspondente; as tarefas mantêm o projeto em que começaram.
3. Em **Tarefas**, filtre por projeto, fonte, estado ou responsável. Abra uma tarefa para conferir objetivo, atividade, tentativas, evidências, revisão e PRs. A conversa de cada tentativa fica a um clique, com seu próprio resultado.
4. Responda aos pedidos em **Precisam de você**, no Início, ou na própria tarefa. A pergunta explica a ação em questão; mudar a entrada ou o código pode exigir uma nova resposta. Permissões e perguntas nativas do Claude levam à conversa em que precisam ser respondidas.

No CTO, **Fontes** inicia uma coleta de Sentry ou KBGen usando os MCPs e a configuração normal do projeto. A coleta tem conversa própria: o CTO recebe metadados no backlog para priorizar, e cada trabalhador lê a issue completa da sua tarefa. Reavaliar a mesma issue conserva as tentativas e evidências anteriores.

O CTO, os trabalhadores e os revisores usam as ferramentas e as permissões normais do projeto. Os papéis organizam o trabalho; as regras de autonomia dos [agentes anteriores](#agentes) continuam próprias daqueles agentes. Ativar a coordenação aguarda os trabalhos anteriores serem conciliados. Conversas manuais, agentes, horários, avisos e links antigos continuam disponíveis.

Uma implementação precisa de evidências de execução e parecer independente; terminar um turno não conclui a tarefa. Para testes no GitHub Actions, a ferramenta de verificação do Maestro pode registrar a execução oficial para o mesmo commit, com o workspace limpo. O revisor confere se os testes ou jobs cobrem o objetivo. Outros comprovantes externos continuam visíveis com sua origem e eventuais limitações.

Comentários seus em PRs vinculados a tarefas voltam à tarefa de origem em uma tentativa própria, conservando o histórico. Configure o login e a integração em **Agentes → Comentários do GitHub**. A tela da tarefa mostra o PR e o andamento dos comentários; eles aguardam as condições de execução e não concedem autorização para novas ações sensíveis.

**Pausar trabalho** segura os próximos disparos. Se um envio ficar incerto, confira a tarefa e a conversa antes de repetir o pedido: o Maestro conserva o registro e não reenvia automaticamente. Desativar a coordenação ou remover um projeto exige conciliar trabalhos e comentários pendentes. Por padrão, o fluxo usa um trabalhador por vez; a configuração avançada permite até dois, mantendo exclusão de checkout e de recursos compartilhados.

## Requisitos

- Linux ou macOS (no Windows não foi testado)
- [Python 3.13](https://www.python.org/) e [uv](https://docs.astral.sh/uv/)
- [Node 22.12 ou mais novo](https://nodejs.org/) e [pnpm](https://pnpm.io/installation)
- git
- O `gh` autenticado é opcional para comentários de PR e verificação oficial de CI do GitHub Actions
- Para o terminal da sessão, bash 4.4 ou mais novo, ou zsh. No macOS o bash da Apple é o 3.2, então o app usa o zsh (ou um bash mais novo do Homebrew, se houver)
- No Linux, o `zenity` (opcional) abre o seletor de pastas nativo. Sem ele, o app usa o navegador de pastas próprio
- [Claude Code](https://code.claude.com/docs) instalado e autenticado na máquina

## Instalação e uso

```bash
git clone https://github.com/vateiixeira/claudio-maestro.git
cd claudio-maestro
uv sync
pnpm --dir frontend install
uv run claudio-maestro
```

Abra **http://localhost:6660**.

Na primeira execução, e sempre que o frontend mudar (depois de um `git pull`, por exemplo), o comando compila o frontend antes de subir. Para usar outra porta: `uv run claudio-maestro --port 7000`.

As sessões continuam rodando quando o backend reinicia: um processo auxiliar (agentd) guarda os processos do agente. Para desligar isso, use `MAESTRO_AGENTD=0`.

Se você roda o backend sob um gerenciador de serviços que encerra o grupo de processos inteiro (o padrão do systemd, `KillMode=control-group`), o agentd cai junto com o backend e as sessões não sobrevivem. O jeito mais simples é o serviço oficial, que já vem configurado para isso (veja [Rodar como serviço](#rodar-como-serviço)). Num serviço feito à mão, use `KillMode=process` na unit, ou rode o backend de modo que o agentd continue vivo depois dele.

Para continuar uma conversa pelo celular, ligue o chip **Remote Control** na barra de opções dela: a sessão passa a aparecer no app do Claude e em claude.ai/code, com a sua conta, e o que passa por lá vai pelos servidores da Anthropic. A escolha vale por conversa e volta sozinha depois de reiniciar o app.

## Rodar como serviço

Para o Maestro subir sozinho e voltar se cair, instale o serviço oficial. No macOS ele sobe quando você entra na conta; no Linux, também no boot, desde que rode `loginctl enable-linger`:

```bash
uv run claudio-maestro service install            # instala e já sobe (use --port para outra porta)
uv run claudio-maestro service status             # se está rodando e onde fica o log
uv run claudio-maestro service uninstall          # para e remove
```

- **Linux:** cria `~/.config/systemd/user/claudio-maestro.service`. Log: `journalctl --user -u claudio-maestro -f`. Para subir no boot sem fazer login, rode `loginctl enable-linger` (o `install` avisa quando falta).
- **macOS:** cria `~/Library/LaunchAgents/io.github.vateiixeira.claudio-maestro.plist`. Log: `~/Library/Logs/claudio-maestro.log`.

O serviço guarda o `PATH` e as variáveis `MAESTRO_*` do momento do install, exceto `MAESTRO_PORT`, `MAESTRO_DEV_PORT` e `MAESTRO_PREVIEW_PORT`: a porta do serviço vem de `--port` (ou de `MAESTRO_PORT`, no momento do install), e as outras duas são de desenvolvimento. Se instalar o Node ou o uv em outro lugar, ou mudar uma variável, rode o `install` de novo: ele reescreve o arquivo e reinicia o app, e as sessões continuam rodando. Elas sobrevivem ao reinício porque o serviço já vem configurado para isso (`KillMode=process` no systemd, `AbandonProcessGroup` no launchd). O comando só mexe no arquivo que ele mesmo criou; se já existir outro com o mesmo nome, ele recusa e avisa.

No Linux, a unit também limita a CPU das sessões, para um teste pesado ou um loop de subagentes não travar a máquina: `CPUWeight` baixo (o desktop tem prioridade em disputa) e `CPUQuota` com o teto de 60% dos núcleos. Ajuste com `MAESTRO_CPU_WEIGHT` e `MAESTRO_CPU_QUOTA` e rode o `install` de novo; quem já tinha o serviço instalado precisa fazer isso uma vez. O `MAESTRO_SESSION_NICE` é lido pelo agentd, que só passa a usar o valor novo depois de reiniciar (`kill $(cat ~/.local/share/claudio-maestro/agentd-v1.lock)` derruba as sessões em andamento; com `MAESTRO_DATA_DIR`, o arquivo fica nessa pasta).

Antes de instalar, feche o Maestro que estiver rodando no terminal: a porta precisa estar livre. Se o terminal usa outra porta (`--port 7000`), passe a mesma ao `install`.

**Se você já tem um serviço próprio.** Se existe uma unit do systemd ou um agente do launchd seu que roda o Maestro, o `install` recusa e diz qual é: dois serviços disputariam a mesma porta e a mesma pasta de dados. Desative o seu antes, para ele também não subir no próximo boot: `systemctl --user disable --now <unit>` no Linux, ou `launchctl bootout gui/$(id -u)/<label>` e remover o arquivo `.plist` no macOS. Depois rode o `install`, com `--port` se a porta não for a padrão (6660).

## Atualizar

O rodapé do menu lateral mostra a versão instalada e avisa quando sai uma versão nova. No aviso, **Atualizar agora** baixa a versão, instala as dependências, compila o frontend e reinicia o app. A página recarrega sozinha, e as sessões continuam rodando enquanto o agentd estiver ligado (o padrão). Com `MAESTRO_AGENTD=0`, o app pede confirmação antes de reiniciar e as sessões caem.

O botão funciona quando:

- o app foi iniciado com `uv run claudio-maestro` (no terminal ou pelo serviço);
- o clone está na `main` (o app faz `git pull`) ou numa tag de release (o app troca para a tag nova);
- não há arquivos versionados alterados;
- algum remoto aponta para o repositório oficial no GitHub;
- `uv` e `pnpm` estão no `PATH` do app.

Se a `main` tiver commits locais que não estão no GitHub, ou se a tag nova não continuar o commit atual, o passo Baixando falha sem mudar nada.

Se algum passo falhar, o app desfaz o que fez e continua na versão anterior. Se nem o desfazer funcionar, o aviso mostra os comandos para recuperar à mão. O log completo fica em `~/.local/share/claudio-maestro/update.log` (ou na pasta de `MAESTRO_DATA_DIR`).

Rodando num terminal, o app reinicia nesse mesmo terminal. Se o botão não estiver disponível, o aviso explica o motivo e mostra os comandos para atualizar à mão:

```bash
git pull
uv sync
pnpm --dir frontend install
```

Depois, pare o app (Ctrl+C) e rode `uv run claudio-maestro` de novo; o frontend é recompilado sozinho. Se usa o serviço, rode `systemctl --user restart claudio-maestro` (Linux) ou `uv run claudio-maestro service install` de novo.

Se a versão nova mudar o agentd e você atualizou pelo botão, um aviso no menu oferece **Reiniciar agentd**, que só fica ativo quando nenhuma sessão está aberta nele. À mão: `kill $(cat ~/.local/share/claudio-maestro/agentd-v1.lock)` (com `MAESTRO_DATA_DIR`, o arquivo fica nessa pasta), o que derruba as sessões em andamento. Ele volta sozinho na próxima sessão. Quem atualiza à mão não vê esse aviso: confira nas notas da versão se o agentd mudou.

Para saber da versão nova, o app consulta a API do GitHub (`api.github.com`) um minuto depois de subir e uma vez por dia. A requisição só lê a última release; nada sobre seus projetos ou conversas é enviado. Para desligar, use `MAESTRO_UPDATE_CHECK=0`. Também dá para acompanhar pelo GitHub: **Watch → Custom → Releases**.

### Versão do Claude e modelos novos

O app usa o `claude` instalado no sistema quando ele é pelo menos tão novo quanto o que vem embutido no SDK. Assim, modelos novos aparecem no Maestro assim que o seu Claude se atualiza, sem esperar uma versão do Maestro. No menu de modelos, **Atualizar o Claude** roda `claude update` e renova a lista. Se o Claude do sistema mudar por fora (o do terminal se atualizou sozinho, ou foi instalado ou removido), o app percebe em até 10 minutos e renova a lista de modelos sozinho. As conversas abertas continuam com a versão com que começaram e passam para a nova quando reconectam.

Para avisar quando sai um Claude novo, o app lê a última versão publicada (canal `latest`, ou `stable` se for o do seu `autoUpdatesChannel`) em `storage.googleapis.com` um minuto depois de subir e uma vez por dia, sem enviar nada seu. Se houver uma versão mais nova que a do seu sistema, o rodapé do menu lateral mostra o aviso, e um clique atualiza. Para desligar a consulta, use `MAESTRO_CLAUDE_CHECK=0`.

Sem o `claude` no sistema, o app usa o embutido. Se você roda o app como serviço, ele guarda o `PATH` do momento do `service install`: se instalar o `claude` depois, em outra pasta, rode o `install` de novo. Para forçar o embutido, use `MAESTRO_CLAUDE_CLI=bundled`. No serviço, a variável só passa a valer rodando `service install` de novo com ela exportada.

## Autenticação

O Cláudio Maestro não faz login e não guarda credenciais. Ele usa a autenticação que o Claude Code já tem na sua máquina, do mesmo jeito que o CLI usa.

Para mostrar o consumo da assinatura no menu lateral, o backend lê o token de login do CLI (`~/.claude/.credentials.json`) e consulta `api.anthropic.com`, como o `/usage` do CLI faz. O token não sai da sua máquina para nenhum outro lugar, e o app nunca o renova. No macOS, onde o CLI guarda o token no Keychain, o medidor mostra "Uso indisponível". Para desligar, use `MAESTRO_USAGE_CHECK=0`.

A Anthropic orienta que produtos de terceiros feitos com o Agent SDK usem [autenticação por chave de API](https://code.claude.com/docs/en/agent-sdk/overview) (`ANTHROPIC_API_KEY`). Escolha a forma de autenticação de acordo com os termos que valem para a sua conta.

## Configuração

| Variável | Para quê | Padrão |
|---|---|---|
| `MAESTRO_PORT` | Porta do app (e do backend, no desenvolvimento) | `6660` |
| `MAESTRO_DEV_PORT` | Porta do Vite, no desenvolvimento | `6600` |
| `MAESTRO_PREVIEW_PORT` | Porta de um segundo Vite, para ver uma worktree em desenvolvimento usando o mesmo backend (veja o `CONTRIBUTING.md`) | desligada |
| `MAESTRO_HOME` | Limite do navegador de pastas; também muda a pasta de dados padrão (`$MAESTRO_HOME/.local/share/claudio-maestro`) | sua pasta pessoal |
| `MAESTRO_DATA_DIR` | Onde fica o banco SQLite (só metadados); vale mais que o `MAESTRO_HOME` | `~/.local/share/claudio-maestro` |
| `MAESTRO_AGENTD` | Com `0`, não inicia o agentd: as sessões novas só vivem enquanto o backend viver (as que já estão num agentd ativo continuam sendo religadas) | ligado |
| `MAESTRO_UPDATE_CHECK` | Com `0`, o app não consulta o GitHub para saber se há versão nova | ligado |
| `MAESTRO_USAGE_CHECK` | Com `0`, o app não consulta o consumo da assinatura | ligado |
| `MAESTRO_CLAUDE_CHECK` | Com `0`, o app não consulta qual é a última versão do Claude (o aviso no menu lateral some) | ligado |
| `MAESTRO_ROUTINES_SCHEDULER` | Com `0`, as rotinas dos agentes não rodam nos horários marcados (o "Rodar agora" continua valendo). Use numa instância isolada com cópia do banco, para os agentes não rodarem em dobro. O nome antigo, `MAESTRO_SPECIALISTS_SCHEDULER`, ainda vale por esta versão; se os dois existirem, o novo vence | ligado |
| `MAESTRO_WORK_DISPATCHER` | Com `0`, não inicia tarefas prontas ou novas tentativas automaticamente; mensagens manuais continuam explícitas. Use `0` em cópia do banco. Sem valor explícito, acompanha `MAESTRO_ROUTINES_SCHEDULER` | acompanha o agendador |
| `MAESTRO_REMOTE_RECONNECT` | Com `0`, não reinicia automaticamente sessões marcadas para Remote Control no início ou após falhas. Não impede mensagens ou ativação manuais. Use `0` em cópia do banco | ligado |
| `MAESTRO_CLAUDE_CLI` | `bundled` faz o app usar sempre o Claude embutido no SDK, em vez do instalado no sistema | escolhe sozinho |
| `MAESTRO_CPU_WEIGHT` | Peso de CPU do serviço systemd, de 1 a 10000: em disputa, o desktop e o navegador passam à frente das sessões. Só vale no serviço, depois de rodar `service install` | `20` |
| `MAESTRO_CPU_QUOTA` | Teto de CPU de todas as sessões somadas, no serviço systemd: `auto` (60% dos núcleos, no mínimo 1), `off` ou um percentual (`800` = 8 núcleos) | `auto` |
| `MAESTRO_SESSION_NICE` | Incremento de `nice` sobre a prioridade com que o agentd roda, limitado a 19, para cada processo do Claude (se o backend já roda com `Nice=5`, as sessões ficam em 15); `0` desliga. Vale também fora do systemd e no macOS | `10` |
| `CLAUDE_CONFIG_DIR` | Pasta de configuração do Claude Code | `~/.claude` |

As portas precisam estar entre 1024 e 65535, fora de 6665 a 6669 (os navegadores bloqueiam essas). O app escuta só em `127.0.0.1`, sempre.

O comando que abre arquivos no editor (padrão: `code`) fica nas Preferências do app.

## Agentes

Os agentes estão sendo refeitos como uma organização por projeto: cada agente passa a ser um arquivo `AGENT.md` com rotinas, chefe e subordinados. A migração dos agentes existentes, como o Sentry e o KBGen, é automática. As telas e esta documentação são refeitas no fim da branch; até lá, o que está descrito abaixo pode não corresponder ao app.

Esta seção descreve as rotinas anteriores, que continuam disponíveis em **Agentes** e em **Agentes e rotinas anteriores** na barra lateral. O fluxo de [CTO e tarefas](#começar-pelo-trabalho) mantém seus próprios vínculos de execução e usa as permissões normais do projeto.

Um agente é uma rotina que você descreve uma vez e o Maestro roda por você, na hora ou nos horários marcados: triar issues, revisar PRs, conferir um deploy. Cadastre na página **Agentes**; cada um tem:

- **Conversas.** Converse diretamente com o agente, retome um assunto ou comece outro contexto. Em Execuções, "Continuar" abre o resultado de uma rotina para perguntas e ajustes.
- **Skill.** O passo a passo que ele segue, num `SKILL.md`.
- **Projetos.** A pasta onde ele trabalha e os outros projetos que ele pode ler.
- **Autonomia.** "Pede ok antes de agir para fora" ou "Vai até o fim".
- **Horários.** Dias da semana e hora. Também dá para rodar na hora, com "Rodar agora".
- **Fila.** Mensagens, pedidos manuais e horários entram na mesma fila. Dá para pausar os próximos disparos, retomar e cancelar o que ainda não começou, sem interromper a execução atual.
- **Segredos.** Variáveis de ambiente (um token, por exemplo) que só a sessão do agente enxerga.
- **Memória.** Os aprendizados que ele reescreve entre execuções e o registro do que já fez, que ele consulta quando precisa.

Onde ficam os arquivos: cada agente tem uma pasta `<pasta de dados>/specialists/<nome>/` (permissão 700), com `SKILL.md`, `aprendizados.md` (até 4.000 caracteres) e `secrets.env` (permissão 600). Os segredos entram só como variáveis de ambiente da sessão do agente, nunca no prompt, e a tela nunca mostra os valores.

A página do agente separa **Conversas**, **Execuções** e **Configuração**. Abrir uma conversa não dispara o modelo; ele só roda quando você envia uma mensagem. O chat mantém o contexto da sessão, enquanto cada rotina começa numa sessão própria. As mensagens pendentes aparecem no chat, com prévia e cancelamento, inclusive depois de recarregar.

Como ele roda:

- Cada agente tem uma conversa principal permanente no topo da barra lateral. Abra-a para pedir algo ou acompanhar os anúncios das execuções; o link "Configurar agente" abre as preferências dele. As execuções ficam no histórico da página Agentes, com o selo "Agente · nome". Ela fica no modo de permissão `default` e não pede ok para editar nem para rodar comandos locais.
- As ações para fora (`git push`, `gh pr create`, `gh pr merge`, `gh issue close`, `gh release` e as que você acrescentar) pedem ok quando a autonomia é "Pede ok antes de agir para fora". O merge (`gh pr merge`), o push para a branch padrão e o push forçado pedem ok sempre, qualquer que seja a autonomia. Um push sem o nome da branch só passa sem ok quando o próprio comando diz a pasta (`cd <pasta> && git push`, `git -C <pasta> push`) e ela não está na branch padrão.
- Agentes não comentam no GitHub: comentários e revisões são recusados, inclusive na autonomia "Vai até o fim". A resposta fica na conversa principal.
- Na página do agente, "Conversar com o agente" abre a mesma conversa principal da barra lateral. "Nova conversa" começa outro contexto. As conversas adicionais podem registrar resultados sem se encerrar; rotinas mantêm sessões próprias.
- Nas rotinas, o agente fecha a própria execução com a ferramenta `concluir`. Se ele não fechar, o Maestro confere o desfecho no fim da sessão.
- Se a execução anterior ainda estiver rodando ou esperando uma decisão, o pedido aguarda na fila. Uma execução marcada como "Esperando você" pela verificação de fechamento também segura a fila até você enviar uma resposta nessa conversa ou finalizá-la. Cada agente executa uma tarefa por vez; agentes diferentes continuam trabalhando em paralelo.
- A fila guarda até 50 pendências por agente. Horários sucessivos se juntam em uma única rotina agendada pendente, para não disparar uma sequência de tarefas iguais ao voltar. O histórico sempre mostra todas as pendências, além das últimas 50 outras execuções.
- A pausa da fila é independente de "Horários ligados": impede os próximos disparos, inclusive os manuais, e mantém as pendências. Desligar os horários também segura as rotinas agendadas que já estavam na fila. As novas sessões das rotinas usam a configuração do agente vigente quando começam; o texto do pedido é o que foi guardado ao enfileirar.
- O agendador pula um novo horário se o uso da assinatura estiver em 90% ou mais e revalida esse limite antes de começar uma rotina que estava na fila. Se o app estava desligado no horário, grava uma execução "perdida". Duas execuções seguidas sem sucesso geram um alerta.
- Os pedidos ainda não enviados sobrevivem ao reinício. Se o envio começou, mas não dá para confirmar o recebimento da mensagem, a fila pausa e deixa um aviso para conferir a conversa antes de retomar ou rodar de novo. O Maestro nunca reenvia automaticamente esse pedido. O texto e as imagens pendentes ficam num arquivo privado `pending-<id>.txt` na pasta do agente e é removido após o envio ou cancelamento; esse conteúdo não entra no SQLite.
- Os avisos que o agente deixa aparecem na Inbox. O histórico das execuções não entra no contexto do agente: o registro é consultado por ferramenta, só quando ele precisa.

### Comentários no PR

Comentários seus nos PRs abertos por um agente voltam à conversa que abriu o PR. Se ela não existir mais, vão à conversa principal. O Maestro consulta os comentários ao iniciar e a cada hora, usando o `gh` já autenticado. Em **Agentes → Comentários do GitHub**, salve o seu login do GitHub para selecionar o autor aceito.

Para receber os comentários sem esperar a consulta:

1. Defina `MAESTRO_HOOKS_PORT` com uma porta livre na máquina do Maestro (por exemplo, `6670`) e reinicie o backend. O receptor escuta só em `127.0.0.1`, separado da API.
2. Salve um segredo em **Comentários do GitHub**. Ele fica em `github-webhook.secret` na pasta de dados, com permissão `600`; a tela só informa se está definido.
3. Se usar um servidor público com Caddy e um túnel SSH até ele, encaminhe apenas o receptor. Exemplo no bloco do domínio no Caddy:

   ```caddyfile
   handle /maestro-hooks/github {
       uri strip_prefix /maestro-hooks
       reverse_proxy 127.0.0.1:6670
   }
   ```

   Na máquina do Maestro, abra o encaminhamento remoto no SSH: `ssh -N -R 127.0.0.1:6670:127.0.0.1:6670 usuario@servidor`. A porta remota precisa coincidir com a do proxy; o último endereço é o receptor local.
4. No repositório do GitHub, crie um webhook com a URL `https://seu-dominio/maestro-hooks/github`, conteúdo `application/json`, o mesmo segredo e os eventos **Issue comments**, **Pull request review comments** e **Pull request reviews**.

O receptor aceita só `POST /github` com assinatura HMAC válida. A API e a interface continuam locais. Comentários também aguardam enquanto o agente trabalha ou sua fila está pausada. O Maestro agrupa comentários do mesmo PR por 60 segundos; uso da assinatura a partir de 90% mantém os comentários na fila. O limite é de dez lotes por PR por dia. Comentários repetidos são ignorados, e a fila sobrevive ao reinício. Se um envio for interrompido sem confirmação, o Maestro avisa na Inbox para conferir a conversa e não repete o pedido automaticamente.

## Segurança

O app executa comandos na sua máquina pelo Claude, então qualquer site aberto no seu navegador é uma ameaça a ele. Por isso ele escuta só em `127.0.0.1`, recusa `Host` e `Origin` de fora, não libera CORS, exige um cabeçalho próprio em toda chamada à API e só aceita caminhos dentro dos projetos cadastrados.

Não exponha o app na rede. Detalhes e como relatar uma falha em [SECURITY.md](SECURITY.md).

## Limitações

- Interface só em português.
- Windows não testado.
- Acesso só local, por uma pessoa.
- A comprovação oficial de CI cobre GitHub.com Actions para um commit exato e limpo; outros provedores não recebem automaticamente esse selo. O parecer ainda precisa avaliar a cobertura dos testes.
- O painel de git não roda hooks do repositório nem assina commits, e fica só para leitura em repositórios com Git LFS ou outro filtro. Rebase, stash e envio forçado ficam com o terminal.

## Contribuindo

Veja [CONTRIBUTING.md](CONTRIBUTING.md). O que pode vir pela frente está no [ROADMAP.md](ROADMAP.md), e o que mudou em cada versão no [CHANGELOG.md](CHANGELOG.md).

## Créditos

Os temas de cores da interface usam as paletas de outros projetos. O Cláudio Maestro não é afiliado, endossado nem patrocinado por eles, e os nomes pertencem aos seus donos.

- **[Dracula](https://draculatheme.com/)**: paleta do tema Dracula, criado por Zeno Rocha e mantido pela comunidade Dracula, sob licença MIT. Os valores foram conferidos em [dracula/visual-studio-code](https://github.com/dracula/visual-studio-code).
- **[Monokai](https://monokai.pro/)**: os filtros Pro, Machine, Octagon, Ristretto e Spectrum do Monokai Pro e o Monokai Classic, criados por Wimer Hazenberg. O Monokai Pro é um produto da Monokai; este projeto usa só os valores de cor das paletas, sem copiar arquivos do tema. Os valores foram conferidos em [loctvl842/monokai-pro.nvim](https://github.com/loctvl842/monokai-pro.nvim) (licença MIT).

Alguns tons de texto secundário foram clareados para manter o contraste mínimo de 4,5:1 (WCAG AA). Os desvios estão comentados em `frontend/src/themes.css`.

## Licença

[MIT](LICENSE).

O Cláudio Maestro é um projeto independente. Não é afiliado, endossado nem patrocinado pela Anthropic. Claude é marca registrada da Anthropic, PBC.
