<?php declare(strict_types=1); require_once __DIR__ . '/security.php'; tabwin2_page_security(); ?><!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#f4f7f8"><meta name="csrf-token" content="<?= htmlspecialchars(tabwin2_csrf_token(), ENT_QUOTES, 'UTF-8') ?>">
  <title>Tabulações prontas · SPPtab</title>
      <link rel="stylesheet" href="assets/app.css?v=15"><link rel="stylesheet" href="assets/brand.css?v=1"><link rel="stylesheet" href="assets/predefined-report.css?v=25"><link rel="stylesheet" href="assets/compact-headings.css?v=1">
</head>
<body>
  <div class="app-shell">
    <aside class="sidebar">
      <a class="brand" href="./" aria-label="SPPtab, início"><span class="brand-mark" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span></span><span><strong>SPPtab</strong><small>saúde em dados</small></span></a>
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
      <div class="sidebar-foot"><span class="source-dot"></span><div><strong>SIA/SUS · SIH/SUS</strong><small>Relatórios prontos</small></div><span class="sidebar-version">v<?= htmlspecialchars(tabwin2_app_version(), ENT_QUOTES, 'UTF-8') ?></span></div>
    </aside>
    <main class="main-content predefined-report-main" id="predefinedMain">
      <header class="topbar"><div class="breadcrumb">Dados públicos <span>/</span> <strong>Tabulações prontas</strong></div><div class="top-tag"><span></span><b>SIA/SUS · SIH/SUS</b></div></header>
      <section class="intro predefined-report-intro"><div class="eyebrow"><span class="eyebrow-line"></span> <span id="predefinedIntroLabel">RELATÓRIOS PRÉ-DEFINIDOS</span></div><h1 id="predefinedIntroTitle">Tabulações prontas para consultar.</h1><p id="predefinedIntroDescription">Escolha um relatório e informe a competência. Novas tabulações serão adicionadas a esta área.</p></section>

      <section class="predefined-catalog" id="predefinedCatalog" aria-labelledby="catalogTitle">
        <div class="catalog-heading"><div><h2 id="catalogTitle">Disponíveis</h2><p>Relatórios preparados para abrir direto na análise.</p></div><span class="catalog-count">6 tabulações</span></div>
        <div class="predefined-card-grid">
          <article class="predefined-card" data-report="sia-pa-producao" role="button" tabindex="0" aria-label="Abrir tabulação: Produção ambulatorial por estabelecimento">
            <div class="predefined-card-top"><span class="predefined-card-icon" aria-hidden="true"><span class="tile-motif"><i></i><i></i><i></i><i></i><i></i></span></span><span class="predefined-card-status"><i></i> Disponível</span></div>
            <div class="predefined-card-content"><div class="predefined-card-eyebrow">SIA/SUS <span>·</span> AMBULATORIAL</div><h3>Produção ambulatorial por estabelecimento</h3><p>Valores apresentados e aprovados por estabelecimento, com detalhamento dos procedimentos SIGTAP.</p></div>
            <div class="predefined-card-tags"><span>UF e município</span><span>Por competência</span><span>Detalhe SIGTAP</span></div>
            <div class="predefined-card-footer"><span>Quantidade · valores · glosas</span><span class="button button-primary" aria-hidden="true">Abrir tabulação <span>→</span></span></div>
          </article>
          <article class="predefined-card" data-report="sih-rd-producao" role="button" tabindex="0" aria-label="Abrir tabulação: Produção hospitalar por estabelecimento">
            <div class="predefined-card-top"><span class="predefined-card-icon" aria-hidden="true"><span class="tile-motif"><i></i><i></i><i></i><i></i><i></i></span></span><span class="predefined-card-status"><i></i> Disponível</span></div>
            <div class="predefined-card-content"><div class="predefined-card-eyebrow">SIH/SUS <span>·</span> HOSPITALAR</div><h3>Produção hospitalar por estabelecimento</h3><p>AIHs e valores por hospital, com detalhamento do procedimento principal, complexidade e financiamento.</p></div>
            <div class="predefined-card-tags"><span>UF e município</span><span>Por competência</span><span>MAC · FAEC</span></div>
            <div class="predefined-card-footer"><span>AIHs · valores · SIGTAP</span><span class="button button-primary" aria-hidden="true">Abrir tabulação <span>→</span></span></div>
          </article>
          <article class="predefined-card" data-report="sih-rd-rejeicoes" role="button" tabindex="0" aria-label="Abrir tabulação: AIHs rejeitadas por estabelecimento">
            <div class="predefined-card-top"><span class="predefined-card-icon" aria-hidden="true"><span class="tile-motif"><i></i><i></i><i></i><i></i><i></i></span></span><span class="predefined-card-status"><i></i> Disponível</span></div>
            <div class="predefined-card-content"><div class="predefined-card-eyebrow">SIH/SUS <span>·</span> AIHs REJEITADAS</div><h3>AIHs rejeitadas por estabelecimento</h3><p>Quantidade e valores associados às AIHs rejeitadas por hospital, com os motivos registrados no processamento.</p></div>
            <div class="predefined-card-tags"><span>UF e município</span><span>Por competência</span><span>Motivos SIH/ER</span></div>
            <div class="predefined-card-footer"><span>AIHs · valores · motivos</span><span class="button button-primary" aria-hidden="true">Abrir tabulação <span>→</span></span></div>
          </article>
          <article class="predefined-card" data-report="sih-sp-profissionais" role="button" tabindex="0" aria-label="Abrir tabulação: Serviços profissionais por AIH">
            <div class="predefined-card-top"><span class="predefined-card-icon" aria-hidden="true"><span class="tile-motif"><i></i><i></i><i></i><i></i><i></i></span></span><span class="predefined-card-status"><i></i> Disponível</span></div>
            <div class="predefined-card-content"><div class="predefined-card-eyebrow">SIH/SUS <span>·</span> SERVIÇOS PROFISSIONAIS</div><h3>Produção profissional por AIH</h3><p>Atos, procedimentos e valores por profissional executor, com consulta do CNS no cadastro oficial do CNES.</p></div>
            <div class="predefined-card-tags"><span>AIH e período</span><span>Hospital e SIGTAP</span><span>Profissional · CNS · CBO</span></div>
            <div class="predefined-card-footer"><span>Atos · valor profissional</span><span class="button button-primary" aria-hidden="true">Abrir tabulação <span>→</span></span></div>
          </article>
          <article class="predefined-card" data-report="sih-rd-ocupacao" role="button" tabindex="0" aria-label="Abrir tabulação: Ocupação de leitos por estabelecimento">
            <div class="predefined-card-top"><span class="predefined-card-icon" aria-hidden="true"><span class="tile-motif"><i></i><i></i><i></i><i></i><i></i></span></span><span class="predefined-card-status"><i></i> Disponível</span></div>
            <div class="predefined-card-content"><div class="predefined-card-eyebrow">SIH/SUS <span>·</span> OCUPAÇÃO DE LEITOS</div><h3>Ocupação de leitos por estabelecimento</h3><p>Leitos SUS do CNES, AIHs processadas e rejeitadas, diárias, ocupação e produção profissional por AIH.</p></div>
            <div class="predefined-card-tags"><span>UF e município</span><span>Por competência</span><span>AIH · CNES · SP</span></div>
            <div class="predefined-card-footer"><span>Leitos · diárias · AIHs</span><span class="button button-primary" aria-hidden="true">Abrir tabulação <span>→</span></span></div>
          </article>
          <article class="predefined-card" data-report="sih-rd-fluxo" role="button" tabindex="0" aria-label="Abrir tabulação: Fluxo de internações por origem e destino">
            <div class="predefined-card-top"><span class="predefined-card-icon" aria-hidden="true"><span class="tile-motif"><i></i><i></i><i></i><i></i><i></i></span></span><span class="predefined-card-status"><i></i> Disponível</span></div>
            <div class="predefined-card-content"><div class="predefined-card-eyebrow">SIH/SUS <span>·</span> FLUXO DE INTERNAÇÕES</div><h3>Origem e destino das internações</h3><p>Veja de quais municípios vêm as AIHs e em quais hospitais e municípios de internação elas são registradas.</p></div>
            <div class="predefined-card-tags"><span>Município de residência</span><span>Município e hospital de destino</span><span>AIHs · valores</span></div>
            <div class="predefined-card-footer"><span>Origem → destino</span><span class="button button-primary" aria-hidden="true">Abrir tabulação <span>→</span></span></div>
          </article>
        </div>
        <p class="catalog-footnote"><span aria-hidden="true">▦</span> Mais relatórios prontos serão incluídos aqui.</p>
      </section>

      <section class="workspace report-workspace" id="reportWorkspace" aria-labelledby="reportWorkspaceTitle" hidden>
        <div class="report-heading"><span class="report-mark" aria-hidden="true"><span class="tile-motif"><i></i><i></i><i></i><i></i><i></i></span></span><div class="report-heading-copy"><h2 id="reportWorkspaceTitle">Produção Ambulatorial · SIA/SUS</h2><p id="reportScopeDescription">Selecione um recorte para abrir o relatório.</p></div><div class="report-heading-actions"><button class="catalog-back-button" id="editReportCriteria" type="button">Alterar recorte</button><button class="catalog-back-button" id="backToCatalog" type="button">← Todas as tabulações</button></div><span class="report-scope"><i></i> DATASUS</span></div>
        <p class="report-method-note" id="reportMethodNote"><strong>Como ler glosas e rejeições:</strong> glosas são a diferença positiva entre o apresentado e o aprovado. A base ambulatorial não traz um total independente de rejeições; esse indicador conta linhas apresentadas com quantidade aprovada igual a zero.</p>
        <div class="report-loader" id="reportLoader" hidden aria-live="polite" aria-busy="true">
          <span class="tile-motif tile-motif--large" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span>
          <div class="report-loader-copy"><strong id="reportStage">Preparando a competência</strong><span id="reportDetail">Aguarde enquanto a base é conferida.</span></div>
          <div class="report-progress" id="reportProgress" hidden><span id="reportProgressFill"></span></div>
          <span class="report-progress-label" id="reportProgressLabel" hidden>0%</span>
          <div class="report-download-queue" id="reportDownloadQueue" hidden><div class="report-download-heading" id="reportDownloadHeading"></div><div class="report-download-files" id="reportDownloadFiles"></div></div>
        </div>
        <div class="report-notice" id="reportNotice" role="status" aria-live="polite" hidden></div>
        <div class="report-empty" id="reportEmpty" role="status"><span class="report-empty-icon" aria-hidden="true">▤</span><strong>Configure o recorte do relatório</strong><span id="reportEmptyMessage">Escolha a UF e a competência. Município, gestão, tipo de prestador, natureza jurídica e complexidade são opcionais.</span><button class="button button-secondary" id="configureReportFromEmpty" type="button">Escolher filtros e competência</button></div>

        <section class="report-result" id="reportResult" hidden aria-live="polite">
          <div class="report-result-heading">
            <div><div class="report-result-title-row"><span class="report-result-dot"></span><h3 id="reportTitle">Produção por estabelecimento</h3><span class="report-count" id="reportCount">0</span></div><p id="reportSubtitle"></p></div>
            <div class="report-result-actions"><button class="button button-secondary" id="backToSummary" type="button" hidden>← Estabelecimentos</button><button class="button button-secondary" id="exportReport" type="button">Baixar CSV</button></div>
          </div>
          <div class="report-kpis" id="reportKpis"></div>
          <div class="report-table-toolbar"><label class="report-search"><span class="sr-only">Buscar no resultado</span><span aria-hidden="true">⌕</span><input id="reportSearch" type="search" placeholder="Buscar estabelecimento ou procedimento"></label><div class="report-table-toolbar-side"><span class="report-table-hint" id="reportTableHint"></span><div class="report-default-actions" id="tableDefaultActions"><button type="button" id="saveTableDefault">Salvar filtros como padrão</button><button type="button" id="clearTableDefault" hidden>Remover padrão</button></div></div></div>
          <div class="report-table-wrap"><table class="report-table"><thead><tr id="reportHeader"></tr></thead><tbody id="reportRows"></tbody><tfoot><tr id="reportTotals"></tr></tfoot></table></div>
          <div class="report-table-pagination" id="reportTablePagination"><span id="reportPageInfo">Página 1 de 1</span><label>Linhas por página <select id="reportPageSize"><option value="50">50</option><option value="100" selected>100</option><option value="250">250</option></select></label><div><button type="button" id="reportPagePrevious" aria-label="Página anterior">←</button><button type="button" id="reportPageNext" aria-label="Próxima página">→</button></div></div>
          <div class="report-notes" id="reportNotes"></div>
        </section>
      </section>
      <footer class="page-footer"><span>SPPtab <span class="footer-separator">·</span> Catálogo de tabulações</span><span>Dados públicos · DATASUS</span></footer>
    </main>
  </div>
  <dialog class="report-setup-dialog" id="reportSetupDialog" aria-labelledby="reportSetupTitle">
    <form id="reportSetupForm" novalidate>
      <div class="setup-dialog-header"><span class="report-mark" aria-hidden="true"><span class="tile-motif"><i></i><i></i><i></i><i></i><i></i></span></span><div><div class="eyebrow"><span class="eyebrow-line"></span> RECORTE DA CONSULTA</div><h2 id="reportSetupTitle">Produção ambulatorial por estabelecimento</h2><p id="reportSetupDescription">Escolha a origem e a competência. Os filtros adicionais são opcionais.</p></div><button class="setup-dialog-close" id="closeReportSetup" type="button" aria-label="Fechar">×</button></div>
      <div class="setup-section"><div class="setup-section-heading"><strong>Local e período</strong><span>A UF define qual arquivo estadual será consultado.</span></div><div class="setup-primary-grid"><label class="field"><span>ESTADO (UF)</span><select id="reportUf" aria-label="Estado de origem dos dados"></select></label><label class="field"><span id="reportMunicipalityLabel">MUNICÍPIO <small>opcional</small></span><select id="reportMunicipality"><option value="">Todos os municípios</option></select></label><label class="field"><span>ANO</span><select id="reportYear" disabled><option value="">Carregando…</option></select></label><div class="field setup-competency-field"><span id="reportMonthLabel">COMPETÊNCIA <small>uma por vez; várias se já baixadas</small></span><select class="setup-month-source" id="reportMonth" multiple hidden aria-hidden="true" tabindex="-1"><option value="">Consultando DATASUS…</option></select><div class="setup-competency-picker" id="reportMonthPicker"><button class="setup-competency-trigger" id="reportMonthTrigger" type="button" aria-expanded="false" aria-controls="reportMonthMenu" aria-labelledby="reportMonthLabel reportMonthTriggerText" disabled><span id="reportMonthTriggerText">Consultando DATASUS…</span><span class="setup-competency-chevron" aria-hidden="true"></span></button><div class="setup-competency-menu" id="reportMonthMenu" role="group" aria-label="Selecionar competências" hidden><div class="setup-competency-menu-head"><span id="reportMonthCount">Nenhuma competência selecionada</span><div><button type="button" id="clearReportMonths">Limpar</button></div></div><div class="setup-competency-options" id="reportMonthOptions"></div></div></div><small class="setup-competency-help">Vários meses só com bases já baixadas. Uma competência pode ser buscada no DATASUS ao abrir.</small></div></div></div>
      <div class="setup-section setup-optional-section"><div class="setup-section-heading"><strong>Filtros adicionais <span>opcionais</span></strong><span>Adicione apenas os critérios que deseja aplicar.</span></div><label class="field setup-add-filter-field"><span>ADICIONAR UM FILTRO</span><select id="addReportFilter"><option value="">Adicionar filtro opcional…</option></select></label><div class="setup-filter-rows" id="reportAdditionalFilters"></div><p class="report-filter-note" id="reportFilterNote">O município e os demais filtros valem para toda a consulta. Use Ctrl no Windows ou Command no Mac para marcar várias categorias no mesmo filtro. Sem seleção, todas são consideradas; filtros diferentes são combinados.</p></div>
      <div class="report-availability setup-availability" id="reportAvailability" role="status">Localizando competências disponíveis…</div>
      <div class="setup-dialog-footer"><div class="setup-default-actions"><button type="button" id="saveSetupDefault">Salvar filtros como padrão</button><button type="button" id="clearSetupDefault" hidden>Remover padrão</button><span id="setupDefaultStatus" role="status"></span></div><button class="button button-secondary" id="cancelReportSetup" type="button">Cancelar</button><button class="button button-primary" id="openReport" type="button" disabled>Gerar relatório <span aria-hidden="true">→</span></button></div>
    </form>
  </dialog>
  <script src="assets/tabulations-nav.js?v=1" defer></script><script src="assets/predefined-report.js?v=40" defer></script>
</body>
</html>
