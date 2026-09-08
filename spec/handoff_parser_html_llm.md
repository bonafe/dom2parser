# Handoff — Geração automática de parser a partir de HTML grande

## Objetivo

Quero construir um sistema que receba uma página HTML potencialmente muito grande, reduza esse HTML sem perder a estrutura relevante para extração de dados e envie essa representação compacta para um LLM. O LLM deve então gerar um parser reutilizável (CSS selectors, XPath, BeautifulSoup/lxml etc.) que rode posteriormente sobre o **HTML original completo**.

A motivação principal é reduzir drasticamente o número de tokens enviados ao LLM.

---

## Problema observado

Páginas reais podem ter centenas de KB ou mais de HTML contendo:

- scripts;
- CSS;
- SVGs;
- imagens inline/base64;
- menus e navegação;
- wrappers de layout;
- atributos irrelevantes (`style`, eventos JS etc.);
- muitos registros repetidos.

O LLM não precisa receber todos os registros repetidos. Ele precisa entender:

1. onde está a estrutura relevante;
2. quais elementos se repetem;
3. qual é a estrutura de cada registro;
4. alguns exemplos representativos;
5. variações/outliers importantes.

---

## Caso real analisado — Banco do Brasil

Foi usado um HTML real de uma página de fatura/cartão do Banco do Brasil.

Características observadas:

- HTML total na ordem de ~236 KB;
- muito código de infraestrutura da página antes da informação relevante;
- scripts, estilos, SVG e imagem inline/base64;
- área relevante da fatura concentrada em duas estruturas `div.lancamentos`;
- cada `div.lancamentos` contém uma tabela com quatro colunas:

```text
Data | Transações | Moeda | Valor
```

Há duas colunas visuais de lançamentos, portanto duas tabelas equivalentes.

Uma linha típica de transação tem formato aproximado:

```html
<tr>
  <td>18/07</td>
  <td>MERCADO OLIVEIRA ...</td>
  <td>R$</td>
  <td>52,74</td>
</tr>
```

Também existem outros tipos de linha usando praticamente a mesma estrutura `<tr><td>...</td>...</tr>`:

### Linha de categoria

```html
<tr>
  <td></td>
  <td class="tituloLancamento">Supermercados</td>
  <td class="tituloLancamento"></td>
  <td class="tituloLancamento"></td>
</tr>
```

### Linha especial

Exemplo:

```text
EMPTY | SALDO FATURA ANTERIOR | R$ | 12.676,08
```

### Linha vazia / espaçador

```text
EMPTY | EMPTY | EMPTY | EMPTY
```

Portanto, **somente comparar a estrutura DOM não é suficiente**. É importante usar também uma assinatura do conteúdo.

---

## Insight principal

A representação enviada ao LLM deveria ser uma espécie de **DOM estrutural destilado**.

Exemplo desejado:

```text
Relevant DOM path:

form#aapf
 > ul#transacaoFormulario.transacao
 > div.transacao-corpo.transacao-apfCENTRAL
 > ul.centralExtrato
 > div#fatura2

REPEATED STRUCTURE:

div.lancamentos × 2
  table > tbody

    tr.header × 1 per table
      td.tituloTabelaLancamento = "Data"
      td.tituloTabelaLancamento = "Transações"
      td.tituloTabelaLancamento = "Moeda"
      td.tituloTabelaLancamento = "Valor"

    tr.section × N
      signature:
        EMPTY | TEXT[class=tituloLancamento] | EMPTY | EMPTY
      examples:
        "Pagamentos/Créditos"
        "Restaurantes"
        "Supermercados"
        "Viagens"

    tr.transaction × N
      signature:
        DATE | TEXT | CURRENCY | MONEY
      examples:
        ["28/07", "PGTO ...", "R$", "-11.966,18"]
        ["18/07", "MERCADO ...", "R$", "52,74"]
        ["17/07", "Supermercado ...", "R$", "135,47"]

    tr.empty × N
      signature:
        EMPTY | EMPTY | EMPTY | EMPTY

    tr.special × N
      examples:
        ["", "SALDO FATURA ANTERIOR", "R$", "12.676,08"]
```

Esse formato transmite quase toda a informação necessária para gerar o parser, mas sem enviar centenas de linhas reais.

---

## Arquitetura proposta

```text
HTML original
   |
   v
[1] Sanitização / cleaning
   |
   v
[2] DOM fingerprint
   |
   v
[3] Content signature
   |
   v
[4] Clusterização de estruturas repetidas
   |
   v
[5] Seleção de amostras representativas + outliers
   |
   v
Compact DOM / Structural Summary
   |
   v
LLM
   |
   v
Parser gerado (XPath / CSS / lxml / BeautifulSoup)
   |
   v
Executar parser no HTML ORIGINAL
   |
   v
Validação
   |
   +--> se falhar: enviar apenas exemplos de falha ao LLM para reparo
```

---

## Etapa 1 — Sanitização

Remover ou reduzir agressivamente elementos que não ajudam na geração do parser:

```text
script
style
svg
noscript
meta
link
comentários
imagens base64/data URLs
```

Remover atributos normalmente irrelevantes:

```text
style
onclick
onchange
onmouseover
outros event handlers
atributos puramente visuais
```

Preservar, em princípio:

```text
id
class
name
role
type
href
data-testid
data-* potencialmente estáveis
```

Também é desejável detectar classes com aparência de hash/geradas dinamicamente e não priorizá-las na geração do parser.

---

## Etapa 2 — DOM fingerprint

Criar uma assinatura estrutural do nó ignorando os valores textuais.

Exemplo:

```html
<tr>
  <td>18/07</td>
  <td>MERCADO</td>
  <td>R$</td>
  <td>52,74</td>
</tr>
```

Pode gerar algo como:

```text
tr(td(TEXT), td(TEXT), td(TEXT), td(TEXT))
```

Ou um hash dessa estrutura.

O fingerprint pode considerar:

- tag;
- classes relevantes;
- id quando útil;
- sequência dos filhos;
- número de filhos;
- tipos de nós filhos.

---

## Etapa 3 — Content signature

Além da estrutura, classificar o conteúdo textual em tipos.

Tipos iniciais possíveis:

```text
EMPTY
TEXT
DATE
DATETIME
INTEGER
DECIMAL
MONEY
CURRENCY
PERCENTAGE
URL
EMAIL
PHONE
BOOLEAN
```

Exemplo:

```text
18/07 | MERCADO OLIVEIRA | R$ | 52,74
```

vira:

```text
DATE | TEXT | CURRENCY | MONEY
```

Isso permite agrupar centenas de registros semanticamente equivalentes mesmo que o conteúdo seja diferente.

---

## Etapa 4 — Clusterização de estruturas repetidas

Agrupar principalmente **siblings** com:

- fingerprint DOM igual ou muito semelhante;
- content signature igual ou compatível;
- mesma posição estrutural relativa.

Idealmente suportar também estruturas quase idênticas, com campos opcionais.

Exemplo:

```text
DATE | TEXT | CURRENCY | MONEY × 123
```

em vez de enviar 123 linhas.

---

## Etapa 5 — Representative sampling

Não manter apenas o primeiro exemplo.

Selecionar algo como:

- primeiro;
- segundo;
- um do meio;
- penúltimo;
- último;
- outliers estruturais;
- outliers de assinatura de conteúdo.

Isso ajuda o LLM a perceber variações reais.

---

## Validação do parser

O parser gerado pelo LLM deve ser executado sobre o HTML **original**, nunca sobre a versão compactada.

O sistema deve medir, por exemplo:

```text
registros encontrados: 123
com data: 122
com descrição: 123
com moeda: 121
com valor: 119
```

Se houver falhas, enviar ao LLM somente:

- parser atual;
- métricas de validação;
- alguns elementos HTML que falharam;
- alguns falsos positivos;
- alguns exemplos corretos.

Pedir ao LLM para corrigir o parser.

Isso cria um loop de reparo barato em tokens.

---

## Bibliotecas/projetos para avaliar antes de implementar tudo

### 1. HtmlRAG

É o candidato mais próximo para a **etapa de cleaning/compressão estrutural inicial**.

Investigar especialmente:

```python
from htmlrag import clean_html
```

Objetivo do teste:

```text
HTML original
→ htmlrag.clean_html()
→ medir caracteres
→ medir tokens
→ verificar se estrutura necessária para gerar XPath/CSS continua preservada
```

Não assumir que ele resolve sozinho a deduplicação do tipo:

```text
<tr>...</tr> × 123 + samples
```

Provavelmente será necessário adicionar uma camada própria de repeat detection / structural clustering.

### 2. AXEtract

Projeto interessante porque se aproxima do objetivo end-to-end:

```text
HTML
→ pruning
→ LLM
→ structured extraction
→ XPath / referência ao DOM
```

Avaliar se pode substituir parte ou toda a arquitetura proposta.

### 3. Agent-E

Usa a ideia de **DOM Distillation** e representação reduzida do DOM para agentes/LLMs.

Pode servir como referência arquitetural, principalmente na ideia de usar accessibility tree / representação semântica em vez de HTML cru.

### 4. Trafilatura

Muito boa para boilerplate removal e extração de conteúdo textual, mas potencialmente inadequada quando a estrutura visual/tabular é essencial para gerar um parser.

### 5. AutoScraper

Interessante quando já existem exemplos dos valores desejados e se quer aprender regras automaticamente.

Não resolve diretamente o cenário em que o sistema ainda precisa descobrir quais dados são relevantes.

### 6. Scrapling

Pode ser útil posteriormente para robustez de seletores e relocalização de elementos quando a página muda.

---

## Estratégia recomendada para protótipo

### Fase A — medir o que HtmlRAG já resolve

Usar o HTML real do Banco do Brasil e comparar:

```text
original bytes/chars/tokens
vs.
clean_html bytes/chars/tokens
```

Também validar se permanecem:

```text
div.lancamentos
table
tr
td
classes relevantes
valores de exemplo
```

### Fase B — implementar Repeat Compressor

Sobre o HTML já limpo:

1. parsear com `lxml` ou `BeautifulSoup`;
2. gerar fingerprint estrutural;
3. gerar content signature;
4. agrupar siblings equivalentes;
5. substituir grupos grandes por resumo + samples;
6. gerar texto/JSON compacto para o LLM.

### Fase C — gerar parser

Prompt sugerido:

```text
You are given a compact structural representation of an HTML document.
Repeated structures marked ×N represent N structurally equivalent elements.
Examples are real samples extracted from the original DOM.

Generate a robust parser using Python + lxml.

Requirements:
- Prefer stable structural selectors.
- Avoid selectors based on dynamic/generated classes.
- Extract the identified repeated records.
- Return structured objects.
- Include validation logic.
- The parser will run against the original full HTML, not this compact representation.
```

### Fase D — feedback loop

Executar parser no HTML completo e retornar apenas erros/outliers para reparo.

---

## Possível formato intermediário

Pode ser texto estruturado ou JSON.

### Exemplo JSON

```json
{
  "node": "div.lancamentos",
  "count": 2,
  "children": [
    {
      "node": "table > tbody > tr",
      "clusters": [
        {
          "kind": "transaction",
          "count": 123,
          "signature": ["DATE", "TEXT", "CURRENCY", "MONEY"],
          "examples": [
            ["18/07", "MERCADO OLIVEIRA", "R$", "52,74"],
            ["17/07", "Supermercado", "R$", "135,47"]
          ]
        },
        {
          "kind": "section",
          "count": 11,
          "signature": ["EMPTY", "TEXT[class=tituloLancamento]", "EMPTY", "EMPTY"],
          "examples": [
            "Restaurantes",
            "Supermercados",
            "Viagens"
          ]
        }
      ]
    }
  ]
}
```

Uma representação assim provavelmente é melhor para o LLM do que HTML minificado puro.

---

## Perguntas a investigar no protótipo

1. Quanto o `HtmlRAG` reduz o HTML real sem configuração extra?
2. Ele mantém `id`, `class`, hierarquia e atributos necessários para construir seletores?
3. Qual representação gera menos tokens: HTML limpo, árvore textual ou JSON?
4. Fingerprint deve incluir classes ou apenas tags + posição estrutural?
5. Como identificar classes geradas dinamicamente?
6. Como agrupar estruturas quase idênticas com campos opcionais?
7. Qual o número ideal de samples por cluster?
8. Como selecionar outliers automaticamente?
9. Como medir confiança do parser gerado?
10. Vale mais gerar XPath/CSS ou código Python completo?
11. AXEtract já resolve uma parte suficiente para evitar implementar isso do zero?
12. Accessibility Tree ajuda mais do que DOM em páginas modernas?

---

## Resultado desejado

A solução deve transformar algo conceitualmente assim:

```text
236 KB de HTML real
```

em algo próximo de:

```text
alguns KB de estrutura relevante
+
cardinalidades
+
assinaturas de conteúdo
+
2–5 exemplos por cluster
+
outliers
```

O LLM recebe apenas essa representação compacta, gera o parser e o sistema valida o parser contra o HTML original.

O ponto principal é separar claramente:

```text
HTML original = fonte de verdade e entrada do parser final
Compact DOM = representação usada apenas para raciocínio do LLM
```

---

## Próximo passo recomendado

Antes de implementar uma biblioteca própria completa:

1. instalar/testar `HtmlRAG` no HTML real;
2. medir redução;
3. inspecionar preservação estrutural;
4. avaliar `AXEtract`;
5. se necessário, implementar somente a camada que aparentemente falta:

```text
repeated subtree detection
+
content signature
+
representative sampling
```

Essa é provavelmente a parte nova e específica do projeto.
