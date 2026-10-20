# Componentes incluídos

- `dbfread` 2.0.7: leitura DBF em streaming; metadados e licença distribuída no diretório `dbfread-2.0.7.dist-info/`.
- `dbf_reader` 0.2.2 e `dbc_reader` 0.1.2: pacotes auxiliares originalmente incluídos; licenças em seus diretórios `*.dist-info/licenses/`.
- `blast-dbf.exe` foi compilado para Windows 64 bits a partir de `blast-dbf.c`, `blast.c` e `blast.h`. O código de `blast-dbf.c` mantém seu aviso de licença original; o código BLAST do zlib está sob a licença em `ZLIB-LICENSE.txt`.
- O fallback puro em Python foi adaptado de `dbc-to-dbf` (licença zlib em `DBC-TO-DBF-LICENSE`).

Os binários e fontes são usados localmente para converter arquivos DBC do DATASUS para DBF.

## Integridade dos binários versionados

SHA-256 dos executáveis atualmente incluídos neste repositório:

- `dbc_reader/bin/blast-dbf.exe`: `927eae2f1a5ffa80e413eab4ad3a5696095862ad63fc671a9e08e258364c12a9`
- `dbc_reader/bin/blast-dbf-linux`: `3a86694fc643c5ca2454565df27c540f3fd2c87fce6ba8aeeb24b3744eb75ea1`
- `dbc_reader/bin/blast-dbf-darwin`: `16d26c07ae6d2fd90fe57e020200d13eb9287b0a41eacc81b1546238d6d8d0f4`

O código-fonte C correspondente está neste diretório. O hash identifica os arquivos versionados, mas não substitui uma recompilação reprodutível: a toolchain e os parâmetros usados para produzir os executáveis existentes não foram verificados nesta revisão.
