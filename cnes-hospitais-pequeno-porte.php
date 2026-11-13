<?php declare(strict_types=1); require_once __DIR__ . '/security.php'; tabwin2_page_security(); ?><!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#f4f7f8"><meta name="csrf-token" content="<?= htmlspecialchars(tabwin2_csrf_token(), ENT_QUOTES, 'UTF-8') ?>">
  <title>Hospitais de pequeno porte · TabulaSUS</title>
  <link rel="stylesheet" href="assets/app.css?v=22"><link rel="stylesheet" href="assets/brand.css?v=1"><link rel="stylesheet" href="assets/predefined-report.css?v=59"><link rel="stylesheet" href="assets/compact-headings.css?v=1"><link rel="stylesheet" href="assets/cnes-hpp.css?v=2">
  <script src="assets/sidebar.js?v=3" defer></script><script src="assets/cnes-hpp.js?v=3" defer></script>
</head>
<body>
  <div class="app-shell">
    <aside class="sidebar" id="spptabSidebar">
      <button class="sidebar-toggle" type="button" aria-controls="spptabSidebar" aria-expanded="true" aria-label="Recolher menu" title="Recolher menu"><span class="sidebar-toggle-icon" aria-hidden="true">‹</span></button>
      <a class="brand" href="./" aria-label="TabulaSUS, início"><span class="brand-mark" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span></span><span><strong>TabulaSUS</strong><small>saúde em dados</small></span></a>
      <div class="nav-label">ESPAÇO DE TRABALHO</div>
      <nav aria-label="Navegação principal">
        <a class="nav-item" data-nav="home" href="index.php"><span class="nav-icon">⌂</span>Início · mapa</a>
        <a class="nav-item active" data-nav="ready" href="tabulacoes-prontas.php" aria-current="page"><span class="nav-icon">▧</span>Tabulações prontas</a>
        <a class="nav-item" data-nav="files" href="index.php?etapa=arquivos"><span class="nav-icon">⌕</span>Buscar arquivos</a>
        <a class="nav-item" data-nav="bases" href="bases.php"><span class="nav-icon">▦</span>Minhas bases</a>
        <a class="nav-item" data-nav="tabular" href="tabular.php"><span class="nav-icon">▤</span>Tabular dados</a>
        <a class="nav-item" data-nav="sigtap" href="sigtap.php"><span class="nav-icon">▦</span>Explorar SIGTAP</a>
        <a class="nav-item" data-nav="saved" href="minhas-tabulacoes.php" id="savedTabulationsNav" hidden><span class="nav-icon">▧</span>Minhas Tabulações</a>
      </nav>
      <div class="sidebar-foot"><div><strong>Fontes oficiais</strong><small>Relatórios prontos</small></div><span class="sidebar-version">v<?= htmlspecialchars(tabwin2_app_version(), ENT_QUOTES, 'UTF-8') ?></span></div>
    </aside>
    <main class="main-content predefined-report-main hpp-main">
      <header class="topbar"><div class="breadcrumb">Dados públicos <span>/</span> <a href="tabulacoes-prontas.php">Tabulações prontas</a> <span>/</span> <strong>Hospitais de pequeno porte</strong></div><div class="top-tag"><b>CNES · Brasil</b></div></header>
      <section class="intro hpp-intro"><div class="eyebrow"><span class="eyebrow-line"></span> ESTRUTURA HOSPITALAR · CNES</div><h1>Hospitais de pequeno porte sem fins lucrativos.</h1><p>Levantamento nacional de hospitais com 5 a 30 leitos cadastrados. Escolha uma competência mensal para consultar os arquivos das 27 unidades da Federação.</p><div class="hpp-current-links"><a href="relatorios/hospitais-pequeno-porte-sem-fins-lucrativos-2026-09.csv" download>Baixar setembro/2026 · 533 hospitais · 10.984 leitos</a><a href="relatorios/LEIA-ME-hospitais-pequeno-porte-2026-09.md" target="_blank" rel="noreferrer">Critérios e fontes</a></div></section>
      <section class="hpp-panel" aria-labelledby="hppControlsTitle">
        <div class="hpp-panel-heading"><div><h2 id="hppControlsTitle">Competência do cadastro</h2><p>O resultado só é gerado quando os arquivos de todos os estados e do Distrito Federal estão publicados.</p></div></div>
        <div class="hpp-controls">
          <label><span>Ano</span><select id="hppYear"></select></label>
          <label><span>Mês</span><select id="hppMonth" disabled><option value="">Consultando o CNES…</option></select></label>
          <button class="button button-primary" id="hppRun" type="button" disabled>Gerar levantamento</button>
        </div>
        <p class="hpp-availability" id="hppAvailability" role="status" aria-live="polite">Consultando competências nacionais do CNES…</p>
      </section>
      <section class="hpp-progress" id="hppProgress" hidden aria-live="polite" aria-busy="true">
        <div class="hpp-progress-meta"><strong id="hppStage">Preparando consulta</strong><span id="hppPercent">0%</span></div>
        <div class="hpp-progress-track"><span id="hppProgressFill"></span></div>
        <p id="hppMessage">A leitura ocorre no computador onde o TabulaSUS está aberto.</p>
      </section>
      <section class="hpp-results" id="hppResults" hidden aria-labelledby="hppResultTitle">
        <div class="hpp-result-heading"><div><div class="eyebrow">LEVANTAMENTO CONCLUÍDO</div><h2 id="hppResultTitle">Hospitais encontrados</h2><p id="hppResultScope"></p></div><button class="button button-secondary" type="button" id="hppExport">Baixar CSV</button></div>
        <div class="hpp-kpis" id="hppKpis"></div>
        <section class="hpp-filters" aria-label="Filtros e classificações">
          <div class="hpp-filters-heading"><div><h3>Filtros e classificações</h3><p>Combine localização, tipo de hospital, natureza jurídica e faixa de leitos.</p></div><button class="hpp-clear-filters" type="button" id="hppClearFilters">Limpar filtros</button></div>
          <div class="hpp-filter-grid">
            <label class="hpp-search"><span>BUSCAR ESTABELECIMENTO</span><input id="hppSearch" type="search" placeholder="Nome, CNES ou município" autocomplete="off"></label>
            <label><span>UF</span><select id="hppUf"><option value="">Todas as UFs</option></select></label>
            <label><span>MUNICÍPIO</span><select id="hppMunicipality"><option value="">Todos os municípios</option></select></label>
            <label><span>TIPO DE HOSPITAL</span><select id="hppUnitType"><option value="">Todos os tipos</option></select></label>
            <label><span>NATUREZA JURÍDICA</span><select id="hppLegalNature"><option value="">Todas as naturezas</option></select></label>
            <label><span>FAIXA DE LEITOS</span><select id="hppBedBand"><option value="">Todas as faixas</option></select></label>
            <label><span>ORDENAR POR</span><select id="hppSort"><option value="state-asc">UF e município</option><option value="name-asc">Estabelecimento · A a Z</option><option value="beds-desc">Total de leitos · maior primeiro</option><option value="beds-asc">Total de leitos · menor primeiro</option></select></label>
          </div>
        </section>
        <div class="hpp-table-summary"><span id="hppTableHint" aria-live="polite"></span><span>O CSV inclui todos os resultados filtrados.</span></div>
        <div class="hpp-table-wrap"><table class="hpp-table"><thead id="hppHead"></thead><tbody id="hppBody"></tbody><tfoot id="hppFoot"></tfoot></table></div>
        <div class="report-table-pagination hpp-pagination" id="hppPagination"><span id="hppPageInfo">Página 1 de 1</span><label>Linhas por página <select id="hppPageSize"><option value="50">50</option><option value="100" selected>100</option><option value="250">250</option></select></label><div><button type="button" id="hppPagePrevious" aria-label="Página anterior">←</button><button type="button" id="hppPageNext" aria-label="Próxima página">→</button></div></div>
        <div class="hpp-notes" id="hppNotes"></div>
      </section>
      <section class="hpp-sources" aria-label="Fontes e critérios">
        <h2>Fontes e critérios do levantamento</h2>
        <p>O arquivo mensal <strong>ST</strong> do CNES fornece o tipo de unidade, natureza jurídica e quantidades de leitos existentes. O recorte considera hospital geral (tipo 05) ou especializado (tipo 07), soma leitos cirúrgicos, clínicos e complementares, e seleciona de 5 a 30 leitos inclusive.</p>
        <p>Como o arquivo não traz um campo independente de certificação filantrópica, a consulta usa o grupo 3 da natureza jurídica do CNES, “entidades sem fins lucrativos”, como aproximação operacional. A natureza jurídica específica segue a tabela CNES NATJUR.CNV; as faixas de 5–9, 10–19 e 20–30 leitos são classificações para consulta. Esses critérios não confirmam CEBAS ou outra certificação. Nomes são consultados no cadastro público atual do CNES; estrutura e natureza são da competência escolhida.</p>
        <div class="hpp-source-links"><a href="https://datasus.saude.gov.br/transferencia-de-arquivos/" target="_blank" rel="noreferrer">DATASUS · Transferência de arquivos</a><a href="https://datasus.saude.gov.br/cnes-estabelecimentos" target="_blank" rel="noreferrer">DATASUS · Estabelecimentos</a><a href="https://datasus.saude.gov.br/cnes-recursos-fisicos/" target="_blank" rel="noreferrer">DATASUS · Recursos físicos</a><a href="https://estabelecimentos.saude.gov.br/pages/estabelecimentos/consulta.jsp" target="_blank" rel="noreferrer">Consulta pública do CNES</a><a href="https://rfsaldanha.github.io/sis/assets/cnes/IT_CNES_1706.pdf" target="_blank" rel="noreferrer">Layout técnico dos arquivos</a></div>
      </section>
    </main>
  </div>
</body>
</html>
