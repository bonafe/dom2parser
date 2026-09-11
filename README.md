# 🗜️ DOM2parser

Biblioteca Python que lê uma página HTML grande (centenas de KB a alguns MB),
encontra as estruturas repetidas que carregam os dados e **gera um parser
verificado** para extraí-las — seletor de registro, locator e nome por campo —
junto de uma representação estrutural compacta da página.

O DOM2parser **não chama nenhum LLM**. A síntese é determinística e, melhor,
verificável: a biblioteca tem em mãos os elementos que quer alcançar, então
escolher um seletor é uma busca medida — gera candidatos, roda contra o
documento original, fica com o que comprovadamente alcança todos os registros.
Um modelo, vendo só sete amostras e um path truncado, estaria chutando.

Os nomes dos campos, a única parte genuinamente semântica, são lidos da própria
página: numa fatura do Banco do Brasil saem `data`, `transacoes`, `moeda` e
`valor` da linha de cabeçalho da tabela. Onde a página não diz nada (WhatsApp
Web, onde toda classe é hash de Stylex), o nome cai para tipo e posição e um
humano renomeia editando o spec. O campo `name_source` registra de onde veio
cada nome, então dá para separar o que foi lido do que foi inferido.

📖 Documentação completa: [arquitetura](https://bonafe.github.io/DOM2parser/architecture.html) ·
[decisões de projeto](https://bonafe.github.io/DOM2parser/decisions.html) ·
[uso e API](https://bonafe.github.io/DOM2parser/usage.html) ·
[resultados](https://bonafe.github.io/DOM2parser/benchmarks.html)

## Instalação

Ainda não publicado no PyPI — instale a partir do repositório clonado:

```bash
git clone https://github.com/bonafe/DOM2parser.git
cd DOM2parser

python3 -m venv .venv
source .venv/bin/activate

pip install -e .
```

> O ambiente do host pode ser *externally-managed* (PEP 668) — o venv acima é
> obrigatório, não opcional, em distros recentes (Debian/Ubuntu).

## Quickstart

```python
import dom2parser

html = open("pagina.html", encoding="utf-8").read()
result = dom2parser.compress(html)

print(result.text)
# REPEATED STRUCTURES (ranked by relevance):
#
# tr > td > div.lancamentos > table > tbody > tr
#   selector: div.lancamentos tr  # matches 154, covers all 154
#   fields:
#     data: td:nth-of-type(1)        # DATE, present in 125/154
#     transacoes: td:nth-of-type(2)  # TEXT, present in 141/154
#     moeda: td:nth-of-type(3)       # CURRENCY, present in 128/154
#     valor: td:nth-of-type(4)       # MONEY, present in 128/154
#   skip header row: ['Data', 'Transações', 'Moeda', 'Valor']
#   row types:
#     [primary] count: 122
#       signature: DATE | TEXT | CURRENCY | MONEY
#       ...

print(result.reduction["reduction_pct"])
# {'chars': 97.3, 'tokens': 97.3}
```

### Extraindo os registros

O parser gerado é **dado, não código** — executado por `lxml`, nunca por
`exec()`. Ele roda contra o HTML **original**, nunca contra a forma compacta:

```python
from dom2parser.parser.executor import execute
from dom2parser.parser.validate import validate

record = result.parser.records[0]
extraction = execute(result.parser, html)[record.name]

print(validate(record, extraction).as_text())
# registros encontrados: 139   (154 casados: 2 cabeçalhos e 13 linhas vazias pulados, cada um com o motivo)
# com data: 123
# com transacoes: 139
# com moeda: 126
# com valor: 126

print(extraction.kept[3].values)
# {'data': '28/07', 'transacoes': 'PGTO DEBITO CONTA...', 'moeda': 'R$', 'valor': '-11.966,18'}
```

Salve o parser com `result.parser.to_yaml()` e recarregue com
`ParserSpec.from_yaml()` — é o ponto onde um humano renomeia um campo cujo nome
saiu ruim.

### Duas coisas que não se deve confundir

`path_display` (`tr > td > div.lancamentos > ...`) **não é um seletor**: ele é
truncado em seis níveis e um `*` dentro de um segmento
(`div[data-testid="list-item-*"]`, `tr#tx-*`) marca a parte de um id/testid que
varia por instância. Serve para localizar a estrutura lendo, e nada mais.
Quem endereça é `record_selector.selector`, que foi medido contra o documento.

`verified` também não é enfeite: um seletor que casa demais sem que haja regra
explicando a sobra vai para `failures` com os quase-acertos, em vez de virar
registro. Parser que funciona pela metade é indistinguível de parser que
funciona.

`compress(html, max_clusters=10, min_cluster_size=2, max_samples_per_cluster=7)`
retorna um `CompactRepresentation` com `.text`, `.json` (schema 2), `.reduction`
e `.parser` (o `ParserSpec` executável). Referência completa em
[usage.html](https://bonafe.github.io/DOM2parser/usage.html#api).

## Como funciona

Pipeline de 10 etapas. As sete primeiras encontram as estruturas repetidas —
sanitização estrutural, dedup de subtree idêntico, fingerprint estrutural com
fallback, content signature, clusterização tolerante, ranking de relevância e
sampling representativo. As três últimas transformam isso num parser: ancoragem
de volta ao documento original, síntese e verificação do seletor, e descoberta
de campos.

Duas correções nessa passagem valem menção, porque as duas foram forçadas por
medição contra ground truth escrito à mão, não por raciocínio:

- **Uma família é incompleta.** O agrupamento por conteúdo abandona linhas que
  classificam de forma atípica: duas transações comuns que começavam com dígito
  viraram `COUNT_LABELED`, viraram cluster singleton e caíram abaixo do
  `min_cluster_size` — a família tinha 152 de 154 linhas. O fecho estrutural as
  recupera.
- **Uma família é profunda demais.** `content_signature` lê o texto dos filhos
  diretos, então o ranking prefere o nível mais fundo em que os filhos ainda
  diferem — um wrapper interno. A sobreposição entre os elementos da família e
  os registros reais era **exatamente zero** em quatro das seis páginas. A
  promoção sobe enquanto cada elemento tem pai próprio, parando onde os irmãos
  convergem no contêiner.

- **Um registro pode ser vários irmãos.** Um item do Hacker News são três `tr`;
  uma entrada de glossário é `dt` + `dd`. O registro é um segmento — âncora
  mais irmãos seguintes até a próxima âncora — e a âncora é a posição do
  período com mais identidade, por isso o `dt` (que tem `id`) e não a `dd`.
- **Um registro pode ser dividido em poucas partes (fan-out para baixo).**
  Cada linha de conversa do WhatsApp são dois `div` sem identidade (ícone,
  texto) *dentro* do registro — o inverso do caso acima. A família caía
  nesses divs e a subida parava um nível cedo demais, porque "pai
  compartilhado" também é o sinal de "cheguei ao contêiner da coleção". O
  que separa as duas situações é o tamanho do fan-out: 46 divs colapsam em
  23 pais de dois em dois; 154 linhas de fatura colapsam em 2 `tbody` de 77
  em 77 — um registro se divide num punhado de partes, nunca em dezenas.

Cada etapa nasceu de comportamento real observado em HTML de produção (bancos,
catálogos de dados abertos, notícias, WhatsApp Web) e no corpus público em
`corpus/` — 11 páginas sem dado pessoal, uma por modo de falha, com
ground truth (incluindo valores lidos à mão da marcação) e um teste-placar em
que toda lacuna conhecida é um `xfail` estrito com a razão medida. Detalhamento
completo, algoritmo por algoritmo, em
[architecture.html](https://bonafe.github.io/DOM2parser/architecture.html) e o
raciocínio por trás de cada decisão em
[decisions.html](https://bonafe.github.io/DOM2parser/decisions.html).

## Desenvolvimento

```bash
# setup
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# rodar toda a suíte
pytest -q

# só o corpus público (roda em qualquer clone, sem dado pessoal)
pytest -q tests/test_corpus.py
```

Dois gabaritos, dois papéis. `tests/fixtures/ground_truth.yaml` cobre as 7
páginas reais de `examples/` e valida **ranking** (`tests/test_eval_harness.py`
garante que o conteúdo relevante sempre pontua acima do ruído dominante
conhecido — menu, widget de filtro, JSON de bootstrap). `corpus/ground_truth.yaml`
cobre as 11 páginas públicas e valida a **síntese do parser**
(`tests/test_corpus.py`): seletor de registro exato, nomes derivados,
quantidade de campos e valores lidos à mão da marcação — a única checagem que
separa "parece certo" de "está certo".

> Os arquivos em `examples/` não estão versionados neste repositório (contêm
> capturas de páginas reais com dados pessoais) — os testes que dependem
> deles só rodam em máquinas que os têm localmente. `corpus/` é público e
> commitado, então `tests/test_corpus.py` roda em qualquer clone.

Um CLI fino existe para inspecionar o pipeline manualmente durante o
desenvolvimento (não é a interface principal do projeto, que é a biblioteca):

```bash
python -m dom2parser.cli caminho/para/pagina.html
```

## Licença

[MIT](LICENSE)
