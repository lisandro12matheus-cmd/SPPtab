# SPPtab

Ferramenta local para buscar, converter e tabular microdados ambulatoriais (SIA/SUS) e hospitalares (SIH/SUS) das unidades da Federação brasileiras.

## Baixar o SPPtab

Baixe `SPPtab-Setup.exe` na página de [Releases](https://github.com/lisandro12matheus-cmd/SPPtab/releases/latest) e abra o arquivo. O executável já contém o SPPtab, o PHP e o Python necessários: ele prepara os componentes automaticamente no computador e inicia o sistema no navegador, sem pedir para extrair ou organizar pastas. A biblioteca de dados permanece na conta do usuário para não ser perdida quando o programa for atualizado. Não é necessário instalar XAMPP, PHP ou Python separadamente. A versão empacotada é destinada a Windows 64 bits.

O SPPtab está em fase inicial e, nesta versão, trabalha com dados ambulatoriais e hospitalares das 27 unidades da Federação. Na busca, escolha uma UF no mapa ou na lista; a consulta estadual começa imediatamente. A lista municipal vem da API oficial do [IBGE](https://servicodados.ibge.gov.br/api/docs/localidades), fica salva em cache neste computador e é opcional. Os arquivos DBC continuam sendo estaduais; a escolha do município só é aplicada depois, na tabulação. Se a lista municipal estiver indisponível, a busca estadual continua normalmente. É necessário acesso à internet para buscar arquivos e definições oficiais do DATASUS. A consulta usa primeiro o [serviço HTTPS de transferência de arquivos do DATASUS](https://datasus.saude.gov.br/transferencia-de-arquivos/) e recorre ao FTP público se necessário. Quando ambos estão indisponíveis, as competências já salvas continuam visíveis na biblioteca local.

O executável ainda não possui assinatura digital. O Windows pode mostrar um aviso de aplicativo não reconhecido na primeira execução. Confira se o download veio da página oficial do projeto e, se desejar, compare o SHA-256 com `SHA256SUM.txt` na mesma versão. Uma assinatura reconhecida exige um certificado de publicação para Windows.

## Fluxo de trabalho

1. **Selecionar DBC:** lista os arquivos que já estão na biblioteca. A busca da etapa anterior identifica arquivos íntegros e evita baixar cópias duplicadas.
2. **Converter para DBF:** converte o DBC selecionado para `uploads/CONVERTIDOS/...`. A tela acompanha o tamanho gravado e atualiza a barra de progresso enquanto o trabalho continua no servidor.
3. **Tabular dados:** a tela mostra listas pesquisáveis para linhas e colunas, além das medidas que podem ser calculadas. Na primeira abertura, pode levar mais tempo enquanto os recursos oficiais são baixados e preparados; a estrutura e as categorias consultadas ficam em cache no navegador para acelerar os próximos acessos. Na seleção por categoria, marque uma ou mais categorias e use **Incluir** ou **Excluir**; as regras ativas ficam visíveis ao lado. As opções de linhas e colunas zeradas, conferência de integridade, salvamento dos registros e tratamento de categorias sem descrição aparecem na mesma tela. “Juntar competências” reúne arquivos convertidos da mesma família e tipo, após conferir se possuem os mesmos campos.

O resultado abre em uma nova aba, que mostra o andamento enquanto a tabulação roda em segundo plano. Ao terminar, exibe colunas e rótulos mapeados, totais por linha e total geral, exportação CSV e opção para baixar o DBF dos registros selecionados. É possível escolher várias medidas se as colunas estiverem como “Não ativa”. A tabulação pode considerar o município escolhido na busca ou todos os municípios da UF.

Na tela de tabulação, use **Salvar combinação** para nomear e guardar linhas, colunas, medidas, filtros e opções do resultado. A área **Minhas Tabulações** aparece na navegação depois que um DBC é selecionado. Os modelos ficam disponíveis para outras competências do mesmo estado e tipo quando os campos e a definição oficial são compatíveis; a competência e o município escolhido não são gravados. As combinações ficam em `uploads/.cache/saved-tabulations.json` (ou dentro da pasta de dados da versão portátil) e acompanham a biblioteca local.

As tabulações leem apenas os campos selecionados no DBF e descartam os registros fora do município escolhido antes de decodificar os demais campos. A busca reutiliza por alguns minutos a lista anual do DATASUS por UF; a biblioteca guarda em `uploads/.cache/` os municípios, as listas de valores, os rótulos oficiais e os resultados recentes. Repetir a mesma configuração retorna o resultado do cache. Os arquivos DBF gerados pela opção “Salvar registros” ficam em `uploads/RESULTADOS/` e são entregues pela rota protegida de download.

## Fontes e organização

- Dados originais: serviço HTTPS ou FTP público do DATASUS, separados em `uploads/{SIA|SIH}/{ano}/{mês}/{família}/`.
- Definições oficiais: `uploads/DEFINICOES/originais/TAB_{SIA|SIH}.zip`; arquivos DEF e referências ativas ficam em `uploads/DEFINICOES/{sistema}/`.
- DBFs convertidos: `uploads/CONVERTIDOS/{sistema}/{ano}/{mês}/{família}/`.
- Progresso temporário dos trabalhos: `uploads/.jobs/`.
- Cache local de valores de colunas e tabulações: `uploads/.cache/`.
- DBFs de registros selecionados para download: `uploads/RESULTADOS/`.
- Os arquivos DBC, DBF, ZIP, JSON e temporários em `uploads` ficam bloqueados para acesso HTTP direto.

## Requisitos

- Apache com uma versão do PHP ainda suportada pelo projeto PHP e `proc_open` habilitado (XAMPP).
- Python 3.10 ou superior para o mecanismo de dados. No XAMPP local, configure `TABWIN2_PYTHON` com o caminho completo de uma versão suportada. Para desenvolvimento sem alterar o ambiente global do Apache, use `uploads/.config/python-path.txt`; esse arquivo é local e não entra no Git. O pacote portátil usa o Python 3.14.8 que acompanha o SPPtab.
- Acesso de saída ao serviço HTTPS do DATASUS ou ao FTP público.

O mecanismo inclui o leitor DBF e o descompactador BLAST necessários para trabalhar sem instalar pacotes Python no ambiente do Apache. Os créditos e licenças dos componentes estão em `engine/vendor/`.

O empacotamento verifica o SHA-256 dos ZIPs oficiais do PHP e do Python antes de extrair, inclusive quando o arquivo já existe no cache de montagem. O Python embutido está fixado na versão 3.14.8 ([fonte oficial e checksum](https://www.python.org/downloads/release/python-3148/)): `a93abe456ab01bd96d7a085b3cdb6566b3063f4241360d114142fbdb07f0a310`. O PHP embutido é 8.5.11; seu checksum está no manifesto oficial de [releases Windows do PHP](https://www.php.net/~windows/releases/releases.json): `0ea96e0d2b9b737a6036f05cf4e95c49313faa6d0f27bd97edb2742503f0c043`. As URLs e os hashes esperados também ficam registrados em `packaging/build.ps1`. Os hashes dos executáveis BLAST incluídos no código estão em `engine/vendor/SOURCES.md`.

## Acesso local e rede

O SPPtab aceita por padrão apenas o acesso local por `localhost`, `127.0.0.1` ou `::1` nas portas locais padrão. Em uma instalação Apache com outro nome ou porta, configure `TABWIN2_ALLOWED_HOSTS` com as autoridades exatas permitidas; não use curingas. O inicializador portátil define automaticamente o host e a porta de loopback escolhidos.

As chamadas da interface usam sessão local e token CSRF. O fallback FTP permanece disponível para redes que bloqueiam HTTPS; para desativá-lo conscientemente, configure `TABWIN2_ALLOW_FTP_FALLBACK=0`. A interface informa quando um arquivo novo veio por HTTPS ou FTP, e o modo usado também fica registrado no manifesto local.
