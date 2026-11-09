<?php declare(strict_types=1); require_once __DIR__ . '/security.php'; tabwin2_page_security(); ?><!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#f4f7f8"><meta name="csrf-token" content="<?= htmlspecialchars(tabwin2_csrf_token(), ENT_QUOTES, 'UTF-8') ?>">
  <title>Tabulações prontas · TabulaSUS</title>
      <link rel="stylesheet" href="assets/app.css?v=22"><link rel="stylesheet" href="assets/brand.css?v=1"><link rel="stylesheet" href="assets/predefined-report.css?v=53"><link rel="stylesheet" href="assets/compact-headings.css?v=1">
  <script src="assets/sidebar.js?v=3" defer></script>
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
    <main class="main-content predefined-report-main" id="predefinedMain">
      <header class="topbar"><div class="breadcrumb">Dados públicos <span>/</span> <strong>Tabulações prontas</strong></div><div class="top-tag"><b>Fontes oficiais</b></div></header>
      <section class="intro predefined-report-intro"><div class="eyebrow"><span class="eyebrow-line"></span> <span id="predefinedIntroLabel">RELATÓRIOS PRÉ-DEFINIDOS</span></div><h1 id="predefinedIntroTitle">Tabulações prontas para consultar.</h1><p id="predefinedIntroDescription">Escolha um relatório e informe a competência. Novas tabulações serão adicionadas a esta área.</p></section>

      <section class="predefined-catalog" id="predefinedCatalog" aria-labelledby="catalogTitle">
        <div class="catalog-heading"><div><h2 id="catalogTitle">Relatórios</h2><p>Escolha a análise que precisa.</p></div><span class="catalog-count" id="catalogCount">19 relatórios</span></div>
        <label class="catalog-search"><span aria-hidden="true">⌕</span><input id="catalogSearch" type="search" placeholder="Buscar relatório, assunto ou fonte" autocomplete="off" aria-label="Buscar tabulações prontas"></label>
        <p class="catalog-no-results" id="catalogNoResults" hidden>Nenhum relatório corresponde à busca.</p>
        <div class="predefined-card-grid">
          <article class="predefined-card" data-category="ambulatorial" data-report="sia-pa-producao" role="button" tabindex="0" aria-label="Abrir tabulação: Produção ambulatorial por estabelecimento">
            <div class="predefined-card-content"><div class="predefined-card-eyebrow">Produção ambulatorial</div><h3>Produção por estabelecimento</h3><p>Compare o apresentado e o aprovado por unidade e abra a composição dos procedimentos.</p></div>
            <div class="predefined-card-footer"><span class="predefined-card-source">SIA/SUS · SIGTAP</span><span class="predefined-card-open" aria-hidden="true">Abrir relatório <span>↗</span></span></div>
          </article>
          <article class="predefined-card" data-category="hospitalar" data-report="sih-rd-producao" role="button" tabindex="0" aria-label="Abrir tabulação: Produção hospitalar por estabelecimento">
            <div class="predefined-card-content"><div class="predefined-card-eyebrow">Produção hospitalar</div><h3>Produção por estabelecimento</h3><p>Acompanhe AIHs e valores por hospital, com abertura dos procedimentos registrados.</p></div>
            <div class="predefined-card-footer"><span class="predefined-card-source">SIH/SUS · SIGTAP</span><span class="predefined-card-open" aria-hidden="true">Abrir relatório <span>↗</span></span></div>
          </article>
          <article class="predefined-card" data-category="hospitalar" data-report="sih-rd-rejeicoes" role="button" tabindex="0" aria-label="Abrir tabulação: AIHs rejeitadas por estabelecimento">
            <div class="predefined-card-content"><div class="predefined-card-eyebrow">Produção hospitalar</div><h3>AIHs rejeitadas</h3><p>Localize rejeições por hospital e consulte os valores e motivos registrados.</p></div>
            <div class="predefined-card-footer"><span class="predefined-card-source">SIH/RJ · SIH/ER</span><span class="predefined-card-open" aria-hidden="true">Abrir relatório <span>↗</span></span></div>
          </article>
          <article class="predefined-card" data-category="hospitalar" data-report="sih-sp-profissionais" role="button" tabindex="0" aria-label="Abrir tabulação: Serviços profissionais por AIH">
            <div class="predefined-card-content"><div class="predefined-card-eyebrow">Serviços profissionais</div><h3>Produção profissional por AIH</h3><p>Consulte atos, procedimentos e valores associados a cada profissional executor.</p></div>
            <div class="predefined-card-footer"><span class="predefined-card-source">SIH/SP · CNES</span><span class="predefined-card-open" aria-hidden="true">Abrir relatório <span>↗</span></span></div>
          </article>
          <article class="predefined-card" data-category="hospitalar" data-report="sih-rd-ocupacao" role="button" tabindex="0" aria-label="Abrir tabulação: Ocupação de leitos por estabelecimento">
            <div class="predefined-card-content"><div class="predefined-card-eyebrow">Capacidade hospitalar</div><h3>Ocupação de leitos</h3><p>Relacione leitos, diárias e AIHs por hospital, com acesso às internações.</p></div>
            <div class="predefined-card-footer"><span class="predefined-card-source">SIH/SUS · CNES</span><span class="predefined-card-open" aria-hidden="true">Abrir relatório <span>↗</span></span></div>
          </article>
          <article class="predefined-card" data-category="hospitalar" data-report="sih-rd-fluxo" role="button" tabindex="0" aria-label="Abrir tabulação: Fluxo de internações por origem e destino">
            <div class="predefined-card-content"><div class="predefined-card-eyebrow">Fluxo assistencial</div><h3>Origem e destino das internações</h3><p>Veja de onde vêm os pacientes e em quais hospitais as AIHs são registradas.</p></div>
            <div class="predefined-card-footer"><span class="predefined-card-source">SIH/SUS</span><span class="predefined-card-open" aria-hidden="true">Abrir relatório <span>↗</span></span></div>
          </article>
          <article class="predefined-card" data-category="vigilancia" data-report="sinan-dengue" role="button" tabindex="0" aria-label="Abrir tabulação: notificações de dengue em Belém">
            <div class="predefined-card-content"><div class="predefined-card-eyebrow">Vigilância epidemiológica</div><h3>Notificações de dengue</h3><p>Consulte semana, unidade notificadora, classificação e residência na mesma tabela.</p></div>
            <div class="predefined-card-footer"><span class="predefined-card-source">SINAN · CNES</span><span class="predefined-card-open" aria-hidden="true">Abrir relatório <span>↗</span></span></div>
          </article>
          <article class="predefined-card" data-category="vigilancia" data-report="sinan-chikungunya" role="button" tabindex="0" aria-label="Abrir tabulação: notificações de chikungunya em Belém">
            <div class="predefined-card-content"><div class="predefined-card-eyebrow">Vigilância epidemiológica</div><h3>Notificações de chikungunya</h3><p>Consulte semana, unidade notificadora e município de residência na mesma tabela.</p></div>
            <div class="predefined-card-footer"><span class="predefined-card-source">SINAN · CNES</span><span class="predefined-card-open" aria-hidden="true">Abrir relatório <span>↗</span></span></div>
          </article>
          <article class="predefined-card" data-category="vigilancia" data-report="sinan-zika" role="button" tabindex="0" aria-label="Abrir tabulação: notificações de zika em Belém">
            <div class="predefined-card-content"><div class="predefined-card-eyebrow">Vigilância epidemiológica</div><h3>Notificações de zika</h3><p>Consulte semana, gestantes, unidade e residência na mesma tabela.</p></div>
            <div class="predefined-card-footer"><span class="predefined-card-source">SINAN · CNES</span><span class="predefined-card-open" aria-hidden="true">Abrir relatório <span>↗</span></span></div>
          </article>
          <article class="predefined-card" data-category="vigilancia" data-report="srag-semanal" role="button" tabindex="0" aria-label="Abrir tabulação: SRAG por semana epidemiológica">
            <div class="predefined-card-content"><div class="predefined-card-eyebrow">Vigilância respiratória</div><h3>SRAG por semana epidemiológica</h3><p>Acompanhe casos graves por agente respiratório, UTI e óbitos, com detalhe por faixa etária.</p></div>
            <div class="predefined-card-footer"><span class="predefined-card-source">SIVEP-Gripe · base semanal</span><span class="predefined-card-open" aria-hidden="true">Abrir relatório <span>↗</span></span></div>
          </article>
          <article class="predefined-card" data-category="ambiental" data-report="sisagua-residual-desinfetante" role="button" tabindex="0" aria-label="Abrir tabulação: Amostras analisadas para residual de desinfetante na água">
            <div class="predefined-card-content"><div class="predefined-card-eyebrow">Vigilância ambiental</div><h3>Residual de desinfetante na água</h3><p>Compare as análises de cloro e dióxido de cloro da vigilância ao mínimo da Diretriz Nacional.</p></div>
            <div class="predefined-card-footer"><span class="predefined-card-source">SISAGUA · IBGE</span><span class="predefined-card-open" aria-hidden="true">Abrir relatório <span>↗</span></span></div>
          </article>
          <article class="predefined-card" data-category="vigilancia" data-report="pqavs-obitos-arboviroses" role="button" tabindex="0" aria-label="Abrir tabulação: óbitos suspeitos de dengue e chikungunya encerrados em até 60 dias">
            <div class="predefined-card-content"><div class="predefined-card-eyebrow">PQA-VS · Indicador 8</div><h3>Óbitos por arboviroses encerrados</h3><p>Óbitos suspeitos de dengue e chikungunya encerrados em até 60 dias da notificação. Meta: 75%.</p></div>
            <div class="predefined-card-footer"><span class="predefined-card-source">SINAN · DENGUE · CHIK</span><span class="predefined-card-open" aria-hidden="true">Abrir relatório <span>↗</span></span></div>
          </article>
          <article class="predefined-card" data-category="vigilancia" data-report="pqavs-contatos-hanseniase" role="button" tabindex="0" aria-label="Abrir tabulação: contatos examinados de casos novos de hanseníase">
            <div class="predefined-card-content"><div class="predefined-card-eyebrow">PQA-VS · Indicador 9</div><h3>Contatos examinados de hanseníase</h3><p>Contatos examinados dos casos novos nas coortes PB e MB, por residência atual. Meta: 82%.</p></div>
            <div class="predefined-card-footer"><span class="predefined-card-source">SINAN · HANSENÍASE</span><span class="predefined-card-open" aria-hidden="true">Abrir relatório <span>↗</span></span></div>
          </article>
          <article class="predefined-card" data-category="vigilancia" data-report="pqavs-contatos-tuberculose" role="button" tabindex="0" aria-label="Abrir tabulação: contatos examinados de casos novos de tuberculose pulmonar">
            <div class="predefined-card-content"><div class="predefined-card-eyebrow">PQA-VS · Indicador 10</div><h3>Contatos examinados de tuberculose</h3><p>Contatos examinados dos casos novos de TB pulmonar com confirmação laboratorial. Meta: 70%.</p></div>
            <div class="predefined-card-footer"><span class="predefined-card-source">SINAN · TUBERCULOSE</span><span class="predefined-card-open" aria-hidden="true">Abrir relatório <span>↗</span></span></div>
          </article>
          <article class="predefined-card" data-category="vigilancia" data-report="pqavs-sifilis-congenita" role="button" tabindex="0" aria-label="Abrir tabulação: sífilis congênita em relação à sífilis em gestantes">
            <div class="predefined-card-content"><div class="predefined-card-eyebrow">PQA-VS · Indicador 11</div><h3>Sífilis congênita × sífilis em gestantes</h3><p>Casos de sífilis congênita em menores de 1 ano sobre casos em gestantes, por residência.</p></div>
            <div class="predefined-card-footer"><span class="predefined-card-source">SINAN · SÍFILIS</span><span class="predefined-card-open" aria-hidden="true">Abrir relatório <span>↗</span></span></div>
          </article>
          <article class="predefined-card" data-category="vigilancia" data-report="pqavs-violencia-raca-cor" role="button" tabindex="0" aria-label="Abrir tabulação: preenchimento de raça/cor nas notificações de violência">
            <div class="predefined-card-content"><div class="predefined-card-eyebrow">PQA-VS · Indicador 14</div><h3>Raça/cor nas notificações de violência</h3><p>Notificações de violência interpessoal e autoprovocada com raça/cor válida. Meta: 95%.</p></div>
            <div class="predefined-card-footer"><span class="predefined-card-source">SINAN · VIOLÊNCIA</span><span class="predefined-card-open" aria-hidden="true">Abrir relatório <span>↗</span></span></div>
          </article>
          <article class="predefined-card" data-category="mortalidade" data-report="sim-mortalidade" role="button" tabindex="0" aria-label="Abrir tabulação: Óbitos por semana">
            <div class="predefined-card-content"><div class="predefined-card-eyebrow">Mortalidade</div><h3>Óbitos por semana</h3><p>Consulte os óbitos registrados e detalhe a causa básica, o capítulo CID-10 e a residência.</p></div>
            <div class="predefined-card-footer"><span class="predefined-card-source">SIM · CID-10</span><span class="predefined-card-open" aria-hidden="true">Abrir relatório <span>↗</span></span></div>
          </article>
          <article class="predefined-card" data-category="materno-infantil" data-report="sim-mortalidade-infantil" role="button" tabindex="0" aria-label="Abrir tabulação: Mortalidade infantil">
            <div class="predefined-card-content"><div class="predefined-card-eyebrow">Saúde materno-infantil</div><h3>Mortalidade infantil</h3><p>Relacione óbitos antes de um ano, faixa de dias, causa básica e nascidos vivos do município de residência.</p></div>
            <div class="predefined-card-footer"><span class="predefined-card-source">SIM · SINASC</span><span class="predefined-card-open" aria-hidden="true">Abrir relatório <span>↗</span></span></div>
          </article>
          <article class="predefined-card" data-category="materno-infantil" data-report="sinasc-maternidades" role="button" tabindex="0" aria-label="Abrir tabulação: Nascimentos e perfil materno-infantil">
            <div class="predefined-card-content"><div class="predefined-card-eyebrow">Saúde materno-infantil</div><h3>Nascimentos e perfil materno-infantil</h3><p>Nascidos vivos, pré-natal, partos, prematuridade e baixo peso em uma tabela por estabelecimento.</p></div>
            <div class="predefined-card-footer"><span class="predefined-card-source">SINASC · CNES</span><span class="predefined-card-open" aria-hidden="true">Abrir relatório <span>↗</span></span></div>
          </article>
        </div>
      </section>

      <section class="workspace report-workspace" id="reportWorkspace" aria-labelledby="reportWorkspaceTitle" hidden>
        <div class="report-heading"><span class="report-mark" aria-hidden="true"><span class="tile-motif"><i></i><i></i><i></i><i></i><i></i></span></span><div class="report-heading-copy"><h2 id="reportWorkspaceTitle">Produção Ambulatorial · SIA/SUS</h2><p id="reportScopeDescription">Selecione um recorte para abrir o relatório.</p></div><div class="report-heading-actions"><button class="catalog-back-button" id="editReportCriteria" type="button">Alterar recorte</button><button class="catalog-back-button" id="backToCatalog" type="button">← Todas as tabulações</button></div><span class="report-scope">DATASUS</span></div>
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
            <div><div class="report-result-title-row"><h3 id="reportTitle">Produção por estabelecimento</h3><span class="report-count" id="reportCount">0</span></div><p id="reportSubtitle"></p></div>
            <div class="report-result-actions"><button class="button button-secondary" id="backToSummary" type="button" hidden>← Estabelecimentos</button><button class="button button-secondary" id="exportReport" type="button">Baixar CSV</button></div>
          </div>
          <div class="report-kpis" id="reportKpis"></div>
          <div class="flow-insight" id="flowOriginInsight" hidden aria-label="Resumo percentual da origem e destino das internações">
            <div class="flow-insight-heading"><strong>Origem e destino</strong><small id="flowInsightNote">Percentuais sobre as AIHs visíveis no recorte.</small></div>
            <div class="flow-insight-stat"><span id="flowOriginLabel">Moradores de Belém</span><strong id="flowOriginValue">—</strong><small id="flowOriginCount">AIHs com residência identificada</small></div>
            <div class="flow-insight-stat"><span id="flowOtherOriginLabel">Moradores de outros municípios</span><strong id="flowOtherOriginValue">—</strong><small id="flowOtherOriginCount">AIHs com residência identificada</small></div>
          </div>
          <div class="report-table-toolbar"><label class="report-search"><span class="sr-only">Buscar no resultado</span><span aria-hidden="true">⌕</span><input id="reportSearch" type="search" placeholder="Buscar estabelecimento ou procedimento"></label><div class="report-table-toolbar-side"><span class="report-table-hint" id="reportTableHint"></span><div class="report-default-actions" id="tableDefaultActions"><button type="button" id="saveTableDefault">Salvar filtros como padrão</button><button type="button" id="clearTableDefault" hidden>Remover padrão</button></div></div></div>
          <div class="report-table-wrap"><table class="report-table"><thead><tr id="reportHeader"></tr></thead><tbody id="reportRows"></tbody><tfoot><tr id="reportTotals"></tr></tfoot></table></div>
          <div class="report-table-pagination" id="reportTablePagination"><span id="reportPageInfo">Página 1 de 1</span><label>Linhas por página <select id="reportPageSize"><option value="50">50</option><option value="100" selected>100</option><option value="250">250</option></select></label><div><button type="button" id="reportPagePrevious" aria-label="Página anterior">←</button><button type="button" id="reportPageNext" aria-label="Próxima página">→</button></div></div>
          <div class="report-notes" id="reportNotes"></div>
        </section>
      </section>
      <footer class="page-footer"><span>TabulaSUS <span class="footer-separator">·</span> Catálogo de tabulações</span><span>Dados públicos · DATASUS</span></footer>
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
  <script src="assets/tabulations-nav.js?v=1" defer></script><script src="assets/predefined-report.js?v=73" defer></script>
</body>
</html>
