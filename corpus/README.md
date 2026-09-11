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
| `wikipedia_countries_by_population.html` | [en.wikipedia.org/wiki/List_of_countries_and_dependencies_by_population](https://en.wikipedia.org/wiki/List_of_countries_and_dependencies_by_population) | Parsoid carimba `id="mwXXX"` único em 75% dos elementos; cabeçalho em `th`; classe de apresentação (`static-row-numbers-norank`) em parte das linhas; lista de referências (252 `li`) competindo com a tabela (242 `tr`) |
| `hackernews_front.html` | [news.ycombinator.com](https://news.ycombinator.com/) | **Fan-out**: cada item são 3 `tr` irmãos (`athing` + subtexto + espaçador); ids numéricos por linha; links com texto e `href` |
| `books_toscrape.html` | [books.toscrape.com](https://books.toscrape.com/) (site de demonstração para scraping) | Cards com imagem, preço com símbolo (`£51.77`), título completo em `a[title]`, nota codificada **na classe** (`p.star-rating.Three`) |
| `quotes_toscrape.html` | [quotes.toscrape.com](https://quotes.toscrape.com/) (site de demonstração) | Lista aninhada por registro (tags); paginação |
| `python_glossary.html` | [docs.python.org/3/glossary.html](https://docs.python.org/3/glossary.html) | **Fan-out** em `dl`: cada termo é `dt` + `dd`; 177 pares |
| `python_library_index.html` | [docs.python.org/3/library/index.html](https://docs.python.org/3/library/index.html) | Lista hierárquica (`toctree-l1` com `toctree-l2` aninhado) |
| `iana_http_status_codes.html` | [iana.org/assignments/http-status-codes](https://www.iana.org/assignments/http-status-codes/http-status-codes.xhtml) | Tabela com `thead`/`th` de verdade e linhas sem classe; coluna com link |

Snapshots baixados em 2026-09-10 com `curl`; não são atualizados automaticamente.
O ground truth em `ground_truth.yaml` descreve o que um humano quer extrair de
cada uma, e `tests/test_corpus.py` mede o que o pipeline entrega contra isso.

Sobre origem e uso: Wikipédia é CC BY-SA 4.0; a documentação do Python é PSF;
IANA é registro público; os dois sites `toscrape.com` existem para serem
raspados. O snapshot do Hacker News contém nomes de usuário públicos
(pseudônimos); se isso incomodar, a página pode ser trocada por outra com o
mesmo padrão de fan-out.
