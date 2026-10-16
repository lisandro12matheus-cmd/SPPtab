<?php declare(strict_types=1); ?><!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#f4f7f8"><title>Resultado da tabulação · SPPtab</title><link rel="stylesheet" href="assets/app.css?v=11"><link rel="stylesheet" href="assets/brand.css?v=1"><link rel="stylesheet" href="assets/tabular-refine.css?v=13"></head>
<body class="result-page"><main class="result-app">
  <header class="result-topbar"><a class="brand result-brand" href="./"><span class="brand-mark" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span></span><span><strong>SPPtab</strong><small>saúde em dados</small></span></a><div class="result-actions"><button class="text-button" id="exportCsv" type="button" disabled>Exportar CSV</button><button class="button button-secondary" id="printTable" type="button" disabled>Imprimir</button></div></header>
  <section class="result-overview"><div class="eyebrow"><span class="eyebrow-line"></span> TABULAÇÃO CONCLUÍDA</div><h1 id="resultTitle">Aguardando resultado…</h1><p id="resultSummary">Esta aba será preenchida assim que a leitura da base terminar.</p><div class="result-badges" id="resultBadges"></div><div class="saved-download" id="savedDownload" hidden></div><div class="result-status" id="resultStatus" role="status">Conectando à aba de tabulação…</div></section>
  <section class="result-tools" id="resultTools" hidden aria-label="Ferramentas da tabela">
    <div class="result-tools-copy"><strong id="visibleSummary">Linhas do resultado</strong><span>Use o ícone no cabeçalho para filtrar valores, como em uma planilha.</span></div>
    <details class="result-column-picker" id="columnPicker">
      <summary><span class="tile-plus" aria-hidden="true">+</span><span>Adicionar coluna</span></summary>
      <div class="result-column-panel">
        <div class="result-column-panel__head"><strong>Dimensões do resultado</strong><span>Acrescente até duas dimensões. As que já estão na tabela não se repetem nas opções.</span></div>
        <div class="result-active-columns" id="activeColumns" aria-label="Dimensões já incluídas"></div>
        <label class="result-column-search"><span class="sr-only">Buscar coluna</span><input id="columnSearch" type="search" placeholder="Buscar coluna disponível" autocomplete="off"></label>
        <div class="result-column-options" id="columnOptions" role="group" aria-label="Colunas disponíveis"></div>
        <div class="result-column-panel__foot"><span id="columnHelp">As colunas adicionadas podem aumentar o tempo de cálculo.</span><button class="button button-primary" id="applyColumns" type="button" disabled>Atualizar resultado</button></div>
      </div>
    </details>
  </section>
  <section class="result-table-panel" id="resultPanel" hidden><div class="result-table-wrap"><table class="result-table"><thead id="resultHead"></thead><tbody id="resultBody"></tbody><tfoot id="resultFoot"></tfoot></table></div></section>
  <footer class="result-footer"><span>Definição oficial · DATASUS / TabWin</span><span>SPPtab</span></footer>
</main><script src="assets/result.js?v=8" defer></script></body></html>
