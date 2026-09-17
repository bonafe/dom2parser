# Corpus público

Páginas reais, sem dado pessoal, **commitadas** no repositório — ao contrário de
`examples/`, que fica só na máquina de quem tem as páginas originais (faturas,
conversas). Por isso este é o único conjunto que roda no CI e o único que
responde, com número, "em quantas páginas isso funciona".

Cada página foi escolhida por um **modo de falha** que exercita, não pelo site.
Toda constante e regra do estágio de parser deveria ter mais de uma página aqui
atrás de si; a que só tem uma é dívida declarada.

| Arquivo | Fonte | Exercita |
|---|---|---|
| `wikipedia_countries_by_population.html` | [en.wikipedia.org](https://en.wikipedia.org/wiki/List_of_countries_and_dependencies_by_population) | Parsoid carimba `id="mwXXX"` único em 75% dos elementos; cabeçalho em `th`; lista de referências (286 `li`) competindo com a tabela (242 `tr`) |
| `wikipedia_olympics.html` | [en.wikipedia.org](https://en.wikipedia.org/wiki/List_of_Olympic_Games_host_cities) | **`rowspan`** (69 células); quatro `table.wikitable` irmãs com as mesmas classes, que só se distinguem por posição |
| `iana_http_status_codes.html` | [iana.org](https://www.iana.org/assignments/http-status-codes/http-status-codes.xhtml) | `thead`/`th` de verdade, linhas sem classe, coluna com link |
| `hackernews_front.html` | [news.ycombinator.com](https://news.ycombinator.com/) | **Fan-out**: cada item são 3 `tr` irmãos (`athing` + subtexto + espaçador); ids numéricos por linha |
| `python_glossary.html` | [docs.python.org](https://docs.python.org/3/glossary.html) | **Fan-out** em `dl`: 177 pares `dt`+`dd`, dois termos dividindo uma definição, e um `¶` de permalink em cada termo |
| `python_library_index.html` | [docs.python.org](https://docs.python.org/3/library/index.html) | Lista hierárquica (`toctree-l1` com `toctree-l2` aninhado); 4 dos 40 itens não têm sublista |
| `books_toscrape.html` | [books.toscrape.com](https://books.toscrape.com/) (demo p/ scraping) | Cards com preço com símbolo (`£51.77`), título completo só em `a[title]`, e invólucro `li.col-xs-6.col-sm-4.col-md-3` sem classe semântica |
| `quotes_toscrape.html` | [quotes.toscrape.com](https://quotes.toscrape.com/) (demo) | `itemprop`; lista aninhada de tags por registro; `span` com pedaços rotulados em vez de prosa |
| `datagov_datasets.html` | [catalog.data.gov](https://catalog.data.gov/dataset) | USWDS: invólucro só com utilitárias (`margin-0`, `display-flex`); metadado como `strong` rótulo + valor; dois invólucros 1:1 com identidade |
| `gov_br_noticias.html` | [gov.br](https://www.gov.br/pt-br/noticias/ultimas-noticias) | Plone, em português. Cada card tem `aria-label` com a **própria manchete** — conteúdo por instância que nunca pode virar nome de campo |
| `github_topics.html` | [github.com/topics](https://github.com/topics) | Nenhuma classe semântica: só utilitárias do Primer (`no-underline`, `rounded`, `color-fg-muted`, `tmp-py-4`). Seletor e nomes têm de cair para posição |
| `chatgpt.html` | chatgpt.com (conversa própria, anonimizada) | Classes Tailwind com valor arbitrário (`bg-[#F4F4F4]!`, `dark:bg-[#303030]!`) que derrubavam o `cssselect` ao virar seletor; só 2 registros na página, poucos demais pra `records.promote()` achar o nível certo (`xfail` conhecido) |

Snapshots baixados em 2026-09-10 com `curl`, exceto `chatgpt.html` (2026-09-17, com todo `<script>` esvaziado antes do commit -- a página trazia sessão logada: token OAuth, e-mail e nome da conta); não são atualizados automaticamente.
O ground truth está em `ground_truth.yaml` e `tests/test_corpus.py` mede o que o
pipeline entrega contra ele — 43 verificações, quatro tipos:

- **registro** — o conjunto de elementos bate com o do ground truth (ou é um
  invólucro 1:1 dele);
- **nomes** — os nomes que a própria página fornece (cabeçalho, `th`,
  `itemprop`, classe) foram derivados;
- **quantidade de campos** — onde a página não nomeia nada, só dá para exigir
  quantos valores um consumidor quer;
- **valores** — o que a extração devolve bate com valores lidos **à mão** da
  marcação. É a única verificação que separa "parece certo" de "está certo".

Lacuna conhecida é `xfail` estrito com a razão medida, nunca uma asserção
afrouxada: consertar vira virar um teste.

Sobre origem e uso: Wikipédia é CC BY-SA 4.0; a documentação do Python é PSF;
IANA, data.gov e gov.br são registros públicos; os dois `toscrape.com` existem
para serem raspados. O snapshot do Hacker News contém nomes de usuário públicos
(pseudônimos); se isso incomodar, a página pode ser trocada por outra com o mesmo
padrão de fan-out.

## Páginas consideradas e descartadas

- **RFC 9110** (`rfc-editor.org`) — 1,1 MB e 6,6 s para sintetizar, e um
  documento de especificação não tem "registros" que um humano saiba enunciar.
  A lição que ela trazia (`dt`+`dd` com decoração) já está coberta pelo
  glossário do Python.
- **Lista de finais da Copa** (Wikipédia) — não tinha `rowspan`; redundante com
  a tabela de população.
- **Agência IBGE** — bloqueada por Cloudflare (HTTP 403).
