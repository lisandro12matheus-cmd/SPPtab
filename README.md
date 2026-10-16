# SPPtab

Ferramenta local para buscar, converter e tabular microdados ambulatoriais (SIA/SUS) e hospitalares (SIH/SUS) das unidades da Federação brasileiras.

## Baixar o SPPtab

Os pacotes para Windows estão na página de [Releases](https://github.com/lisandro12matheus-cmd/SPPtab/releases/latest). O pacote portátil pode ser extraído em uma pasta e iniciado pelo `SPPtab.exe`; não é necessário instalar PHP, Python ou XAMPP separadamente. A versão empacotada atualmente é destinada a Windows 64 bits.

O SPPtab está em fase inicial e, nesta versão, trabalha com dados ambulatoriais e hospitalares das 27 unidades da Federação. Na busca, escolha uma UF no mapa ou na lista; a consulta estadual começa imediatamente. A lista municipal vem da API oficial do [IBGE](https://servicodados.ibge.gov.br/api/docs/localidades), fica salva em cache neste computador e é opcional. Os arquivos DBC continuam sendo estaduais; a escolha do município só é aplicada depois, na tabulação. Se a lista municipal estiver indisponível, a busca estadual continua normalmente. É necessário acesso à internet para buscar arquivos e definições oficiais do DATASUS. A consulta usa primeiro o [serviço HTTPS de transferência de arquivos do DATASUS](https://datasus.saude.gov.br/transferencia-de-arquivos/) e recorre ao FTP público se necessário. Quando ambos estão indisponíveis, as competências já salvas continuam visíveis na biblioteca local.

O pacote portátil ainda não possui assinatura digital. O Windows pode mostrar um aviso de aplicativo não reconhecido ao executar o programa pela primeira vez. Confira se o download veio da página oficial do projeto e compare o SHA-256 com o arquivo `SPPtab-Portable-SHA256SUM.txt` da mesma versão. Assinar futuras versões com um certificado reconhecido é a solução para identificar o publicador no Windows; uma assinatura criada pelo próprio projeto não eliminaria o aviso.

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

- Apache/PHP 8 com `proc_open` habilitado (XAMPP).
- Python 3.10 ou superior. Se o Apache não localizar o Python, defina `TABWIN2_PYTHON` antes de iniciar o Apache.
- Acesso de saída ao serviço HTTPS do DATASUS ou ao FTP público.

O mecanismo inclui o leitor DBF e o descompactador BLAST necessários para trabalhar sem instalar pacotes Python no ambiente do Apache. Os créditos e licenças dos componentes estão em `engine/vendor/`.
