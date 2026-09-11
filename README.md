# 🗜️ DOM2parser

Biblioteca Python que comprime páginas HTML grandes (centenas de KB a alguns MB)
numa representação estrutural compacta — preservando hierarquia, cardinalidade de
estruturas repetidas, assinaturas de conteúdo e exemplos representativos — para que
um programa com LLM gere um parser (CSS/XPath/lxml) reutilizável, sem gastar
milhares de tokens com HTML bruto.

O DOM2parser **não** chama nenhum LLM e não gera parsers — essa é a etapa
seguinte, a cargo do programa consumidor. Este projeto é só a compressão.

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
#   count: 122
#   signature: DATE | TEXT | CURRENCY | MONEY
#   examples:
#     ['28/07', 'PGTO DEBITO CONTA...', 'R$', '-11.966,18']  # numeric-outlier
#     ...

print(result.reduction["reduction_pct"])
# {'chars': 96.8, 'tokens': 96.8}
```

Um `*` dentro de um segmento do path (`div[data-testid="list-item-*"]`,
`tr#tx-*`) marca a parte de um id/testid que varia por instância — um
índice de lista virtualizada, um id de banco, um slug. Não é para ser usado
literalmente num seletor: prefira `[data-testid^="list-item-"]` ou o
próximo segmento estável.

`compress(html, *, max_clusters=10, min_cluster_size=2, max_samples_per_cluster=7)`
retorna um `CompactRepresentation` com `.text` (representação em texto), `.json`
(mesma informação estruturada) e `.reduction` (contagem de chars/tokens original
vs. compacto). Referência completa da API em
[usage.html](https://bonafe.github.io/DOM2parser/usage.html#api).

## Como funciona

Pipeline de 7 etapas — sanitização estrutural, dedup de subtree idêntico,
fingerprint estrutural com fallback, content signature, clusterização
tolerante, ranking de relevância e sampling representativo. Cada etapa nasceu
de um comportamento real observado ao rodar contra HTML de produção (bancos,
catálogos de dados abertos, notícias, WhatsApp Web) — não de especulação. Veja
o detalhamento em [architecture.html](https://bonafe.github.io/DOM2parser/architecture.html)
e o raciocínio por trás de cada decisão em
[decisions.html](https://bonafe.github.io/DOM2parser/decisions.html).

## Desenvolvimento

```bash
# setup
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# rodar toda a suíte (inclui regressão contra os 6 exemplos reais em examples/)
pytest -q
```

A suíte de testes usa `tests/fixtures/ground_truth.yaml` como gabarito: para
cada página real em `examples/`, anota qual seletor CSS corresponde ao
conteúdo relevante e qual corresponde ao ruído dominante conhecido (menu,
widget de filtro, JSON de bootstrap). `tests/test_eval_harness.py` é a suíte
de regressão principal do projeto: verifica que o ranking sempre coloca o
conteúdo relevante acima do ruído conhecido.

> Os arquivos em `examples/` não estão versionados neste repositório (contêm
> capturas de páginas reais com dados pessoais) — para rodar a suíte completa
> localmente é preciso fornecer seus próprios exemplos seguindo o formato
> anotado em `tests/fixtures/ground_truth.yaml`.

Um CLI fino existe para inspecionar o pipeline manualmente durante o
desenvolvimento (não é a interface principal do projeto, que é a biblioteca):

```bash
python -m dom2parser.cli caminho/para/pagina.html
```

## Licença

[MIT](LICENSE)
