# Continuar o Vini7 Vibing: fechar o marco 6 e o MVP

Você vai continuar a construção do Vini7 Vibing neste repositório (`/home/vi/dev/vini7-vibing`). Uma sessão anterior orquestrou os marcos 0 a 5 e parte do 6 com subagentes. Você continua do mesmo jeito.

## Leia antes

- `CLAUDE.md`: regras, portas, comandos, segurança, subagentes e revisão em duas camadas.
- `ROADMAP.md`: fonte única do progresso. Marcos 0 a 5 concluídos; marco 6 em andamento.
- `docs/prompts/2026-09-28-construir-mvp.md`: requisitos, identidade visual e todos os fatos verificados do SDK (seções "Fatos verificados...").
- `docs/design/project/*.dc.html`: telas aprovadas.

Rode `git log --oneline | head -20` e `git status` para ver o estado.

## Como trabalhar

Você só orquestra; não implemente você mesmo.

- Para cada tarefa: um subagente `implementer` (Opus, raciocínio baixo) implementa com testes antes do código; um `reviewer` (Sonnet, raciocínio médio) revisa; se reprovar, mande as correções ao mesmo implementador (`SendMessage`) e peça ao mesmo revisor para olhar de novo.
- Commit por tarefa aprovada, no formato do `CLAUDE.md` (`[Tipo] Título` em português). Marque os itens no `ROADMAP.md` com `[x]` e a data, e atualize a contagem.
- No fim do marco: `milestone-reviewer` (Opus, raciocínio alto) revisa o marco inteiro; depois um teste real contra o SDK seguindo os cuidados do `CLAUDE.md` (haiku, pasta temporária, `setting_sources=[]` quando fizer sentido, variáveis `CLAUDE*` removidas, sessões apagadas no fim).
- Tarefas que mexem só em `backend/` e só em `frontend/` podem rodar em paralelo. Diga a cada subagente que não toque na outra pasta.
- Frontend só com `pnpm` (nunca `npx` nem `yarn`).
- Subagentes não sobem servidores nem encerram processos. Se o sistema de permissões bloquear algo, não contorne: peça ao usuário.
- O usuário já autorizou seguir até o fim do MVP sem parar, exceto se algo falhar ou precisar de decisão dele.
- Relatórios ao usuário em português, curtos, separando o que foi rodado e visto passar do que só foi escrito.

## Onde parou

Marco 6: tarefas 1 (robustez do backend), 2 (robustez do frontend) e 4 (acessibilidade e fontes locais) concluídas, revisadas e commitadas. Falta a tarefa 3, a revisão profunda do marco e o teste real.

## O que falta no marco 6

Tarefa 3 (backend e frontend):

- **Seletor de pasta nativo:** botão "Escolher pasta…" na tela de novo projeto. O backend (rota `POST /api/fs/pick`) abre `zenity --file-selection --directory` (instalado; GNOME/Wayland) com argumentos em lista, sem shell, tempo limite de alguns minutos, começando na pasta pessoal; devolve o caminho escolhido (validado dentro da pasta pessoal) ou "cancelado". O navegador de pastas atual continua como alternativa. Protegido como as outras rotas (Host, Origin, `X-Vibing`).
- **Prévia de repositórios** na tela de novo projeto usando a mesma descoberta do projeto (3 níveis, pastas ignoradas, teto de 50).
- **Aviso na interface** quando um projeto passa de 50 repositórios.
- **Tela de preferências:** comando do editor (`editor_command`, lista de strings), dias para ocultar sessões (`finished_after_days`). Usa `GET /api/state` e `PUT /api/state/preferences`.
- **"HEAD solto"** indicado também no navegador de pastas (o backend precisa informar `detached` em `/api/fs/dirs`).
- **Caminhos com espaços, acentos e links simbólicos** para fora da pasta pessoal: testes cobrindo projetos, navegador, diff e abrir no editor.
- **Frontend ajustado** ao que a tarefa 1 mudou: diff de arquivo sumido responde 404 com "O arquivo não existe mais."; texto do limite da assinatura "Limite da assinatura atingido. Libera às HH:MM."; aviso "Conversa compactada" e "Parte do histórico não pôde ser lida.".

Depois: revisão profunda do marco 6, teste real contra o SDK (inclua: modo inicial herdado do `defaultMode` do usuário, interromper subagente em segundo plano com `stop_task`, mensagens de login expirado e limite), e marque o marco 6 como concluído. Com isso o MVP (marcos 0 a 6) termina.

## Ao terminar o MVP

Avise o usuário com um resumo do que foi entregue, como subir o app (comandos no `CLAUDE.md`, acesso em `http://localhost:6600`) e um roteiro curto de teste manual. Os marcos 7 (agrupador de sessões) e 8 (progresso de planos) só começam quando o usuário pedir; as perguntas em aberto deles estão no `ROADMAP.md`.

## Pontos em aberto a lembrar

- O design aprovado mostra "Permitir" e "Negar" direto nos cartões de "Todas as sessões". Não está em nenhum marco; pergunte ao usuário se entra.
- Não usar o Vibing no próprio repositório do Vibing com o backend em `--reload`: cada edição reinicia o servidor.
