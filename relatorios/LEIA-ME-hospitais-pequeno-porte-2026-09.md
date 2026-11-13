# Levantamento nacional de hospitais de pequeno porte

**Competência:** setembro de 2026  
**Consulta executada em:** 13 de novembro de 2026  
**Resultado:** 533 estabelecimentos em 23 UFs; 10.984 leitos existentes no recorte.  
**Arquivo:** `hospitais-pequeno-porte-sem-fins-lucrativos-2026-09.csv`

## Critérios

- Arquivos mensais estaduais **ST** do Cadastro Nacional de Estabelecimentos de Saúde (CNES), publicados pelo DATASUS.
- Foram conferidos os arquivos das 27 unidades da Federação antes do cálculo.
- Tipos de unidade CNES: **05 — Hospital geral** e **07 — Hospital especializado**.
- Natureza jurídica: código iniciado por **3**, grupo CNES **entidades sem fins lucrativos**.
- A natureza jurídica específica segue a tabela oficial CNES `NATJUR.CNV` (por exemplo, associação privada, fundação privada ou organização social).
- Leitos: soma de **QTLEITP1** (cirúrgicos), **QTLEITP2** (clínicos) e **QTLEITP3** (complementares); mínimo de 5 e máximo de 30, inclusive.
- Para facilitar filtros e comparações, os resultados também são classificados em **5 a 9**, **10 a 19** e **20 a 30 leitos**. Essas faixas são categorias analíticas deste levantamento, não classes oficiais do CNES.
- O quantitativo usa leitos existentes do cadastro, sem limitar a leitos SUS.

## Interpretação

“Entidades sem fins lucrativos” é uma aproximação operacional para o recorte pedido de hospitais filantrópicos. O arquivo mensal não informa, em campo independente, a certificação filantrópica; portanto esta lista não confirma CEBAS ou outro certificado. Nomes foram obtidos do cadastro público atual do CNES e podem ter mudado desde setembro de 2026. O código CNES identifica cada estabelecimento.

O arquivo CSV apresenta as classificações de natureza jurídica e faixa de leitos para permitir filtros e ordenações na análise.

## Fontes

- [DATASUS — Transferência de arquivos](https://datasus.saude.gov.br/transferencia-de-arquivos/)
- [DATASUS — CNES: Estabelecimentos](https://datasus.saude.gov.br/cnes-estabelecimentos)
- [DATASUS — CNES: Recursos Físicos](https://datasus.saude.gov.br/cnes-recursos-fisicos/)
- [Consulta pública do CNES](https://estabelecimentos.saude.gov.br/pages/estabelecimentos/consulta.jsp)
- [Layout técnico CNES (ST): campos de leitos e natureza jurídica](https://rfsaldanha.github.io/sis/assets/cnes/IT_CNES_1706.pdf)
