# Direções visuais (2026-09-30)

Três propostas para tirar o app do preto chapado sem mudar layout, rotas nem comportamento. Cada mockup mostra a mesma tela: barra lateral, chat com tabela, bloco de comando com saída, código inline, e o painel Detalhes com o Resumo.

Canvas publicado: https://claude.ai/artifact/P6VMGDraFb22rLUi31Rf86

| Arquivo | Direção |
|---|---|
| `A-camadas.dc.html` | A, conservadora: elevação por camadas, paleta quase igual |
| `B-tingido.dc.html` | B, neutros frios tingidos e cor semântica por área |
| `C-hierarquia.dc.html` | C, neutros quentes e hierarquia forte com acentos |

O usuário escolheu a opção A em 2026-09-30. Ela foi aplicada no app inteiro no marco 14 do roadmap.

## O que vale para as três

- **Chat é a superfície mais clara entre as colunas.** Barra lateral e Detalhes ficam um degrau abaixo, então as três áreas se separam sem precisar de borda forte.
- **Links e caminhos saem do verde.** Passam para azul (`info-soft`). Código inline fica neutro, com fundo próprio.
- **Comando e saída têm fundos diferentes.** O comando fica no fundo mais escuro e a saída um degrau acima, com borda entre os dois.
- **Tabela com cabeçalho preenchido** e cantos arredondados.
- **"Falta" vem antes de "Feito"** na fase aberta, com texto mais forte. "Feito" fica menor e apagado. Na opção A, "Falta" e "Aberta" se destacam pelo peso e pela cor `fg`, não pelo laranja.
- **Um terceiro tom de texto, `subtle`,** para metadados e rótulos, abaixo de `fg-muted`. Todos os tons de texto passam AA (4,5:1) sobre a superfície mais clara de cada opção.
- **Laranja na barra lateral só no contador do projeto e na linha da conversa que espera você.** Linhas paradas ou concluídas perdem o triângulo.

## Regras de cor

| Cor | Quando usar | Nunca usar em |
|---|---|---|
| Verde (`primary`) | Ação principal (Enviar), em execução, turno concluído, sucesso, barra de contexto abaixo de 80%, marca | Links, código inline, texto de corpo, títulos |
| Laranja (`secondary`) | Precisa de você: "Sua vez", contador do Inbox, item "Falta", fase aberta, contexto acima de 80%, modo sem perguntas | Decoração, linhas da barra lateral sem pendência |
| Azul (`info`) | Links, caminhos de arquivo, não lida, foco do campo (só em B) | Estados de execução ou erro |
| Vermelho (`diff-del`) | Erro, comando que falhou, linha removida | Avisos que não são erro |
| Neutro | Todo o resto: corpo, código inline, tabelas, rótulos, cartões | Nada a evitar |

## Opção A: camadas

Mesma paleta neutra, cinco degraus de superfície bem espaçados e bordas um pouco mais claras.

```css
@theme {
  --color-bg: #0b0b0c;          /* era #0a0a0a  barra lateral, Detalhes */
  --color-surface: #131315;     /* novo         chat */
  --color-panel: #19191c;       /* era #111111  barras, blocos */
  --color-card: #1f1f23;        /* era #171717 */
  --color-elevated: #26262b;    /* era #1a1a1a  campo, código inline */
  --color-line: #2a2a30;        /* era #262626 */
  --color-line-strong: #3b3b43; /* era #333333 */
  --color-fg: #f4f4f5;          /* era #fafafa */
  --color-fg-muted: #a1a1aa;    /* era #a1a1a1 */
  --color-fg-subtle: #94949d;   /* novo */
  --color-info-soft: #93c5fd;   /* novo  links */
  --color-primary-tint: rgb(74 222 128 / 0.10);    /* novo */
  --color-secondary-tint: rgb(251 146 60 / 0.12);  /* novo */
}
```

- **Barra lateral:** fundo `bg`, item ativo em `card`.
- **Chat:** fundo `surface`. Mensagem do usuário em `card` com borda forte. Trilho em `line-strong`, mais visível.
- **Bloco de comando:** cabeçalho `panel`, comando `bg`, saída `panel`.
- **Turno concluído:** borda verde translúcida.
- **Detalhes:** Propriedades num cartão dividido em dois grupos, sessão e ambiente. Fase concluída afunda para `bg`, fase aberta sobe para `card`. Status vira pílula com borda.
- **Composer:** campo em `elevated`, seletores sem fundo.

## Opção B: tingido frio

Neutros com leve tom azul-ardósia. O azul vira a cor de navegação e foco, o que libera o verde para estado.

```css
@theme {
  --color-bg: #0b0d12;
  --color-surface: #10131a;     /* novo  chat */
  --color-panel: #151923;
  --color-card: #1a1f2b;
  --color-elevated: #212735;
  --color-line: #252b38;
  --color-line-strong: #343c4d;
  --color-fg: #eef1f6;
  --color-fg-muted: #9ca5b6;
  --color-fg-subtle: #8c95ab;   /* novo */
  --color-info-soft: #93c5fd;   /* novo */
  --color-info-tint: rgb(96 165 250 / 0.12);       /* novo  anel de foco */
  --color-primary-tint: rgb(74 222 128 / 0.10);
  --color-secondary-tint: rgb(251 146 60 / 0.12);
  --color-details: #0e1118;     /* novo  fundo do Detalhes */
}
```

- **Barra lateral e Detalhes:** dois tons escuros diferentes, então as três colunas se distinguem.
- **Chat:** caminhos em azul. Cabeçalho da tabela em mono caixa-alta, sem linhas verticais.
- **Bloco de comando:** o `$` fica azul. Saída um degrau acima do comando.
- **Turno concluído:** faixa com fundo verde translúcido.
- **Detalhes:** Propriedades viram lista com divisória entre linhas. Status em pílula colorida, verde para Concluída e laranja com ponto para Aberta. "Falta" em laranja com círculo vazio. "Feito" com tique cinza.
- **Composer:** campo focado com borda e anel azul. Seletores com fundo `panel`.

## Opção C: hierarquia

Neutros levemente quentes e mais contraste de tipo. Menos rótulos em mono caixa-alta: só ficam os de turno e da lista de ações.

```css
@theme {
  --color-bg: #0e0d0b;
  --color-surface: #161511;     /* novo  chat */
  --color-panel: #1c1b17;       /* barras, composer */
  --color-card: #22211c;
  --color-elevated: #2a2823;
  --color-line: #2f2d27;
  --color-line-strong: #423f36;
  --color-fg: #f5f3ee;
  --color-fg-muted: #aaa59a;
  --color-fg-subtle: #9a9588;   /* novo */
  --color-info-soft: #93c5fd;   /* novo */
  --color-primary-tint: rgb(74 222 128 / 0.10);
  --color-secondary-tint: rgb(251 146 60 / 0.12);
  --color-details: #11100d;     /* novo */
}
```

- **Tipografia:** corpo do chat sobe para 14,5px com entrelinha 1,65. Títulos de seção, rótulos de bloco e "Turno concluído" passam de mono caixa-alta para Geist semibold.
- **Mensagem do usuário:** borda verde translúcida, avatar verde e nome em verde claro. É o único lugar onde o verde marca autoria.
- **Bloco de comando:** status "falhou" vira pílula vermelha. O `$` fica verde.
- **Detalhes:** Resumo abre com a manchete em 15px semibold. Fase aberta tem título em semibold. Status em pílula com borda. "Falta" em laranja vem primeiro.
- **Composer:** fundo `panel` próprio. Seletores viram um grupo segmentado com rótulo e valor, por exemplo "Modelo Sonnet 5". Botão Enviar com ícone. Campo focado com anel verde.

## O que muda em cada componente

| Componente | Mudança |
|---|---|
| `style.css` | Tokens novos acima. `.markdown a` e `code` deixam o verde. Tabela com `th` preenchido e borda arredondada. Classe para `fg-subtle` |
| `ConversationThread` | Fundo `surface` no chat. Faixa de turno concluído com tinta verde |
| `UserMessage` | Fundo e borda conforme a opção. Em C, acento verde |
| `TextBlock` | Largura máxima de 68 caracteres para leitura. Em C, corpo maior |
| `BashTool` | Três fundos: cabeçalho, comando e saída. Status em pílula (C) |
| `ActionGroup` | Chips com fundo. Rótulos em `subtle` |
| `RailNode` | Trilho em `line-strong`. Nó de erro em vermelho, como hoje |
| `MessageComposer` | Fundo do campo e anel de foco. Seletores agrupados em C |
| `DetailsPanel` | Fundo próprio. Propriedades agrupadas (A e C) ou com divisórias (B) |
| `DigestSection` | Status em pílula. "Falta" antes de "Feito", em laranja. Fase concluída esmaecida |
| `AppSidebar`, `SidebarSessionRow` | Triângulo laranja só onde há pendência. Item ativo um degrau acima |
