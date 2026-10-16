<?php declare(strict_types=1); ?><!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#f4f7f8"><title>Tabulação · SPPtab</title><link rel="stylesheet" href="assets/app.css?v=12"><link rel="stylesheet" href="assets/brand.css?v=1"><link rel="stylesheet" href="assets/tabular-refine.css?v=15"><link rel="stylesheet" href="assets/presets.css?v=1"></head>
<body><div class="app-shell"><aside class="sidebar"><a class="brand" href="./"><span class="brand-mark" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span></span><span><strong>SPPtab</strong><small>saúde em dados</small></span></a><div class="nav-label">ESPAÇO DE TRABALHO</div><nav aria-label="Navegação principal"><a class="nav-item" href="index.php"><span class="nav-icon">⌕</span>Buscar arquivos</a><a class="nav-item" href="bases.php"><span class="nav-icon">▦</span>Minhas bases</a><a class="nav-item active" href="tabular.php"><span class="nav-icon">▤</span>Tabular dados</a><a class="nav-item" id="savedTabulationsNav" href="minhas-tabulacoes.php" hidden><span class="nav-icon">▧</span>Minhas Tabulações</a></nav><div class="sidebar-foot"><span class="source-dot"></span><div><strong>Definições oficiais</strong><small>DATASUS · TabWin</small></div></div></aside>
<main class="main-content tabular-main"><header class="topbar"><div class="breadcrumb">Dados públicos <span>/</span> <strong>Tabulação</strong></div><div class="top-tag"><span></span><b id="tabLocationName">Localidade</b></div></header><section class="intro"><div class="eyebrow"><span class="eyebrow-line"></span> LEITURA E TABULAÇÃO</div><h1>Uma etapa de cada vez.</h1><p>Selecione uma base local, converta o DBC para DBF acompanhando o progresso e depois monte sua tabulação com as definições oficiais.</p></section>
<div class="wizard-steps" role="list"><button class="wizard-step active" data-stage="1" type="button"><span>01</span><strong>Selecionar DBC</strong></button><i></i><button class="wizard-step" data-stage="2" type="button"><span>02</span><strong>Converter para DBF</strong></button><i></i><button class="wizard-step" data-stage="3" type="button"><span>03</span><strong>Tabular dados</strong></button></div>
<section class="workspace stage-panel" id="stage1"><div class="step-heading"><span class="step-number">01</span><div><h2>Escolha o arquivo DBC</h2><p>Somente arquivos que já estão na sua biblioteca aparecem aqui.</p></div></div><div class="tab-form"><label class="field"><span>ARQUIVO IMPORTADO</span><select id="sourceFile"><option value="">Carregando biblioteca…</option></select></label><div class="definition-status" id="sourceDetails">A biblioteca está sendo carregada.</div><button class="button button-primary" id="toConvert" disabled>Continuar para conversão <span aria-hidden="true">→</span></button><div class="notice" id="notice1" hidden role="status"></div></div></section>
<section class="workspace stage-panel" id="stage2" hidden><div class="step-heading"><span class="step-number">02</span><div><h2>Converter DBC para DBF</h2><p>O DBF é a versão descompactada que a tabulação consegue ler.</p></div></div><div class="tab-form"><div class="definition-status" id="convertDetails">Selecione um arquivo na etapa anterior.</div><div class="convert-state" id="convertState" hidden><div class="progress-meta"><strong id="progressLabel">Preparando conversão</strong><span id="progressPercent">0%</span></div><div class="progress-track" role="progressbar" aria-label="Progresso da conversão" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><span id="progressFill"></span></div><small id="progressCopy">Aguarde enquanto o arquivo é convertido.</small></div><button class="button button-primary" id="startConvert" disabled>Converter arquivo <span aria-hidden="true">→</span></button><button class="button button-primary" id="toTabulate" hidden>Continuar para tabulação <span aria-hidden="true">→</span></button><div class="notice" id="notice2" hidden role="status"></div></div></section>
<section class="workspace stage-panel" id="stage3" hidden>
  <div class="step-heading"><span class="step-number">03</span><div><h2>Monte sua tabulação</h2><p>Escolha o que aparece nas linhas, nas colunas e qual medida será calculada.</p></div></div>
  <div class="tab-form">
    <div class="definition-status" id="definitionStatus">Preparando arquivo convertido e definição…</div>
    <div class="schema-loading" id="schemaLoading" hidden role="status" aria-live="polite" aria-busy="true">
      <span class="brand-mark schema-loading__mark" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span></span>
      <div class="schema-loading__copy"><span class="schema-loading__eyebrow">PREPARANDO TABULAÇÃO</span><strong id="schemaLoadingTitle">Alinhando os campos à definição oficial</strong><p id="schemaLoadingText">Na primeira vez, pode levar um pouco mais de tempo enquanto os recursos oficiais são baixados e preparados. Depois, a definição fica salva no cache deste navegador.</p><span class="schema-loading__track" aria-hidden="true"><span></span></span></div>
    </div>
    <div class="tabulation-layout" id="tabControls" hidden>
      <section class="choice-panel">
        <div class="choice-heading"><h3>Linhas</h3><p>O que será listado uma linha por vez.</p></div>
        <label class="field"><span>BUSCAR LINHA</span><input id="rowSearch" type="search" placeholder="Digite para localizar" autocomplete="off"></label>
        <select id="rowField" class="choice-list" size="7" aria-label="Escolha o que mostrar nas linhas"></select>
        <small class="list-status" id="rowListStatus" role="status"></small>
      </section>
      <section class="choice-panel">
        <div class="choice-heading"><h3>Colunas <span>opcional</span></h3><p>Divida o resultado por outra informação.</p></div>
        <label class="field"><span>BUSCAR COLUNA</span><input id="columnSearch" type="search" placeholder="Digite para localizar" autocomplete="off"></label>
        <select id="columnField" class="choice-list" size="7" aria-label="Escolha como dividir as colunas"></select>
        <small class="list-status" id="columnListStatus" role="status"></small>
        <div class="column-filter" id="columnValueFilter" hidden>
          <label class="field"><span>VER APENAS UMA CATEGORIA</span><select id="columnValue" disabled><option value="">Todas as categorias</option></select></label>
          <small id="columnValuesStatus" role="status">Escolha uma coluna para carregar as categorias.</small>
        </div>
      </section>
      <section class="choice-panel increment-panel" id="incrementSection" hidden>
        <div class="choice-heading"><h3>O que calcular? <span>(incremento)</span></h3><p>Frequência usa a quantidade padrão. “Número de registros” conta linhas.</p></div>
        <div class="increment-meta"><span>Marque uma ou mais medidas</span><strong id="incrementCount">1 selecionado</strong></div>
        <div class="increment-options" id="incrementOptions" role="group" aria-label="Medidas para calcular"></div>
        <small class="list-status">Para marcar mais de uma medida, deixe Colunas como “Não ativa”.</small>
      </section>
    </div>
    <section class="selection-builder" id="filterOptions" hidden>
      <div class="section-label"><div><h3>Seleções por categoria</h3><p>Escolha uma informação e marque as categorias que deseja manter ou excluir.</p></div></div>
      <div class="selection-layout">
        <div class="selection-available">
          <label class="field"><span>INFORMAÇÃO PARA FILTRAR</span><select id="filterField" disabled><option value="">Escolha uma informação…</option></select></label>
          <div class="category-search-row">
            <label class="field"><span>LOCALIZAR CATEGORIA</span><input id="filterSearch" type="search" placeholder="Digite um nome ou código" disabled></label>
          <button class="button button-secondary" id="locateCategory" type="button" disabled>Localizar categoria</button>
          </div>
          <div class="field"><span>CATEGORIAS DISPONÍVEIS</span><div id="filterValue" class="category-list" role="group" aria-label="Selecione uma ou mais categorias" aria-disabled="true"></div></div>
          <small class="selection-hint">Marque uma ou mais categorias e clique em Incluir ou Excluir.</small>
          <small class="list-status" id="filterStatus" role="status">Escolha uma informação para ver as categorias disponíveis.</small>
        </div>
        <div class="selection-actions" aria-label="Ações para as categorias selecionadas">
          <button class="button button-secondary" id="includeSelection" type="button" disabled>Incluir <span aria-hidden="true">→</span></button>
          <button class="button button-secondary exclude-action" id="excludeSelection" type="button" disabled>Excluir <span aria-hidden="true">→</span></button>
        </div>
        <div class="selection-active">
          <div class="active-title"><div><h3>Seleções ativas</h3><p>Categorias selecionadas e regras aplicadas.</p></div><span id="filterCount">Nenhuma</span></div>
          <small class="active-list-label">CATEGORIAS SELECIONADAS</small>
          <div class="active-filters" id="activeFilters" aria-live="polite"></div>
        </div>
      </div>
    </section>
    <details class="option-disclosure" id="fileOptions" hidden>
      <summary><strong>Juntar competências</strong><span id="fileCount">1 base selecionada</span></summary>
      <div class="disclosure-body">
        <p class="disclosure-help">Some mais de uma competência no mesmo resultado. Os arquivos precisam ser do mesmo tipo e ter a mesma estrutura; o sistema confere isso antes de processar.</p>
        <div class="file-add-row">
          <label class="field"><span>ESCOLHA OUTRA COMPETÊNCIA</span><select id="extraFile" disabled><option value="">Nenhuma base disponível</option></select></label>
          <button class="button button-secondary" id="addFile" type="button" disabled>Juntar ao resultado</button>
        </div>
        <div class="selected-files" id="selectedFiles" aria-live="polite"></div>
        <small class="disclosure-help" id="fileStatus" role="status">A primeira base é a que você escolheu na etapa inicial.</small>
      </div>
    </details>
    <section class="advanced-options" id="advancedOptions" hidden>
      <div class="tabwin-options" id="tabwinOptions">
      <div class="section-label"><div><h3>Opções do resultado</h3><p>Escolha como lidar com categorias sem valores ou sem descrição.</p></div></div>
      <div class="option-checks">
        <label><input id="suppressRows" type="checkbox" checked><span>Suprimir linhas zeradas<small>Oculta categorias cujo total é zero.</small></span></label>
        <label><input id="suppressColumns" type="checkbox" checked><span>Suprimir colunas zeradas<small>Oculta categorias de coluna cujo total é zero.</small></span></label>
        <label class="option-help"><input id="testCrc" type="checkbox"><span>Testar integridade do arquivo (CRC)<small>Compara o DBC original com o DBF convertido. Pode levar mais tempo.</small></span></label>
        <label class="option-help"><input id="saveRecords" type="checkbox"><span>Salvar registros selecionados<small>Gera um DBF para baixar com os registros que passaram pelos filtros.</small></span></label>
      </div>
      <fieldset class="unclassified-options"><legend>Categorias sem descrição na definição</legend>
        <label><input type="radio" name="unclassified" value="ignore" checked><span>Ignorar</span></label>
        <label><input type="radio" name="unclassified" value="include"><span>Incluir em uma linha agrupada</span></label>
        <label><input type="radio" name="unclassified" value="discriminate"><span>Discriminar pelos códigos</span></label>
      </fieldset>
      </div>
    </section>
    <label class="municipality-check" id="municipalityWrap" hidden><input id="municipalityFilter" type="checkbox" checked><span><strong id="municipalityTitle">Filtrar município escolhido</strong><small id="municipalityDescription">Município selecionado na tela inicial</small></span></label>
    <div class="tabulation-actions"><button class="button button-secondary" id="savePresetButton" type="button" disabled><span aria-hidden="true">＋</span> Salvar combinação</button><button class="button button-primary run-button" id="runButton" disabled>Gerar tabulação <span aria-hidden="true">↗</span></button></div>
    <small class="run-help">O resultado será aberto em uma nova aba.</small>
    <div class="notice" id="notice3" hidden role="status"></div>
    <dialog class="preset-dialog" id="presetDialog" aria-labelledby="presetDialogTitle"><div class="preset-dialog-card"><button class="preset-dialog-close" id="closePresetDialog" type="button" aria-label="Fechar">×</button><span class="preset-dialog-mark" aria-hidden="true"><span class="tile-motif"><i></i><i></i><i></i><i></i><i></i></span></span><p class="preset-dialog-eyebrow">MODELO REUTILIZÁVEL</p><h3 id="presetDialogTitle">Salvar combinação</h3><p class="preset-dialog-copy">Dê um nome fácil de reconhecer. A competência e a localidade escolhida ficam de fora, então você pode usar o modelo em outros meses compatíveis.</p><form id="presetForm"><label class="field"><span>NOME DA COMBINAÇÃO</span><input id="presetName" type="text" maxlength="80" placeholder="Ex.: Produção por município e procedimento" required autocomplete="off"></label><div class="preset-dialog-context" id="presetDialogContext"></div><div class="preset-dialog-actions"><button class="button button-secondary" id="cancelPreset" type="button">Cancelar</button><button class="button button-primary" id="confirmPreset" type="submit">Salvar combinação</button></div><div class="notice" id="presetNotice" hidden role="status"></div></form></div></dialog>
  </div>
</section>
<section class="workspace tab-result" id="resultPanel" hidden>
  <div class="results-head"><div><div class="results-title"><h3>Resultado da tabulação</h3><span class="count-badge" id="resultCount">0</span></div><p id="resultSummary"></p></div><button class="text-button" id="exportCsv" type="button">Exportar CSV</button></div>
  <div class="file-table-wrap"><table class="file-table result-table"><thead id="resultHead"></thead><tbody id="resultBody"></tbody><tfoot id="resultFoot"></tfoot></table></div>
</section><footer class="page-footer"><span>SPPtab <span class="footer-separator">·</span> tabulação em 3 etapas</span><span>Dados públicos do Ministério da Saúde / DATASUS</span></footer></main></div><script src="assets/tabulations-nav.js?v=1" defer></script><script src="assets/tabular.js?v=31" defer></script></body></html>
