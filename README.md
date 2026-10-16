# SPPtab

Ferramenta local para buscar, converter e tabular microdados ambulatoriais (SIA/SUS) e hospitalares (SIH/SUS) do Pará.

## Baixar o SPPtab

Os pacotes para Windows estão na página de [Releases](https://github.com/lisandro12matheus-cmd/SPPtab/releases/latest). O pacote portátil pode ser extraído em uma pasta e iniciado pelo `SPPtab.exe`; não é necessário instalar PHP, Python ou XAMPP separadamente. A versão empacotada atualmente é destinada a Windows 64 bits.

O SPPtab está em fase inicial e, nesta versão, trabalha com dados ambulatoriais e hospitalares do Pará. É necessário acesso à internet para buscar arquivos e definições oficiais do DATASUS.

## Fluxo de trabalho

1. **Selecionar DBC:** lista os arquivos que já estão na biblioteca. A busca da etapa anterior identifica arquivos íntegros e evita baixar cópias duplicadas.
2. **Converter para DBF:** converte o DBC selecionado para `uploads/CONVERTIDOS/...`. A tela acompanha o tamanho gravado e atualiza a barra de progresso enquanto o trabalho continua no servidor.
3. **Tabular dados:** a tela mostra listas pesquisáveis para linhas e colunas, além das medidas que podem ser calculadas. Na seleção por categoria, marque uma ou mais categorias e use **Incluir** ou **Excluir**; as regras ativas ficam visíveis ao lado. As opções de linhas e colunas zeradas, conferência de integridade, salvamento dos registros e tratamento de categorias sem descrição aparecem na mesma tela. “Juntar competências” reúne arquivos convertidos da mesma família e tipo, após conferir se possuem os mesmos campos.

O resultado abre em uma nova aba, com colunas e rótulos mapeados, totais por linha e total geral, exportação CSV e opção para baixar o DBF dos registros selecionados. É possível escolher várias medidas se as colunas estiverem como “Não ativa”. O filtro de Belém permanece disponível na tela principal.

As tabulações leem apenas os campos selecionados no DBF e guardam em `uploads/.cache/` as listas de valores e os resultados recentes. Repetir a mesma configuração retorna o resultado do cache. Os arquivos DBF gerados pela opção “Salvar registros” ficam em `uploads/RESULTADOS/` e são entregues pela rota protegida de download.

## Fontes e organização

- Dados originais: FTP público do DATASUS, separados em `uploads/{SIA|SIH}/{ano}/{mês}/{família}/`.
- Definições oficiais: `uploads/DEFINICOES/originais/TAB_{SIA|SIH}.zip`; arquivos DEF e referências ativas ficam em `uploads/DEFINICOES/{sistema}/`.
- DBFs convertidos: `uploads/CONVERTIDOS/{sistema}/{ano}/{mês}/{família}/`.
- Progresso temporário dos trabalhos: `uploads/.jobs/`.
- Cache local de valores de colunas e tabulações: `uploads/.cache/`.
- DBFs de registros selecionados para download: `uploads/RESULTADOS/`.
- Os arquivos DBC, DBF, ZIP, JSON e temporários em `uploads` ficam bloqueados para acesso HTTP direto.

## Requisitos

- Apache/PHP 8 com `proc_open` habilitado (XAMPP).
- Python 3.10 ou superior. Se o Apache não localizar o Python, defina `TABWIN2_PYTHON` antes de iniciar o Apache.
- Acesso de saída ao FTP público do DATASUS.

O mecanismo inclui o leitor DBF e o descompactador BLAST necessários para trabalhar sem instalar pacotes Python no ambiente do Apache. Os créditos e licenças dos componentes estão em `engine/vendor/`.
