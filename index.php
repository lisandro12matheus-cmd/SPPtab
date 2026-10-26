<?php
declare(strict_types=1);
require_once __DIR__ . '/security.php';
tabwin2_page_security();
?><!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#f4f7f8">
  <meta name="csrf-token" content="<?= htmlspecialchars(tabwin2_csrf_token(), ENT_QUOTES, 'UTF-8') ?>">
  <title>SPPtab · DATASUS</title>
  <link rel="stylesheet" href="assets/app.css?v=16">
  <link rel="stylesheet" href="assets/file-selection.css?v=1">
  <link rel="stylesheet" href="assets/brand.css?v=1">
  <link rel="stylesheet" href="assets/launch.css?v=3">
  <link rel="stylesheet" href="assets/search-loading.css?v=3">
  <link rel="stylesheet" href="assets/compact-headings.css?v=1">
  <script src="assets/launch-gate.js?v=1"></script>
</head>
<body>
  <div class="launch-splash" id="launchSplash" role="status" aria-live="polite">
    <img class="launch-splash__logo" src="assets/spptab-logo.svg?v=1" alt="SPPtab">
    <div class="launch-splash__loader" aria-hidden="true">
      <span class="launch-splash__tile"></span><span class="launch-splash__tile"></span><span class="launch-splash__tile"></span>
      <span class="launch-splash__tile"></span><span class="launch-splash__tile"></span>
    </div>
    <p class="launch-splash__message" id="launchMessage">Carregando recursos</p>
  </div>
  <div class="app-shell state-not-selected">
    <aside class="sidebar">
      <a class="brand" href="./" aria-label="SPPtab, início">
        <span class="brand-mark" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span></span>
        <span><strong>SPPtab</strong><small>saúde em dados</small></span>
      </a>
      <div class="nav-label">ESPAÇO DE TRABALHO</div>
      <nav aria-label="Navegação principal">
        <a class="nav-item active" data-nav="home" href="index.php" aria-current="page"><span class="nav-icon">⌂</span>Início · mapa</a>
        <a class="nav-item" data-nav="ready" href="tabulacoes-prontas.php"><span class="nav-icon">▧</span>Tabulações prontas</a>
        <a class="nav-item" data-nav="files" href="index.php?etapa=arquivos"><span class="nav-icon">⌕</span>Buscar arquivos</a>
        <a class="nav-item" data-nav="bases" href="bases.php"><span class="nav-icon">▦</span>Minhas bases</a>
        <a class="nav-item" data-nav="tabular" href="tabular.php"><span class="nav-icon">▤</span>Tabular dados</a>
        <a class="nav-item" data-nav="sigtap" href="sigtap.php"><span class="nav-icon">▦</span>Explorar SIGTAP</a>
        <a class="nav-item" data-nav="saved" href="minhas-tabulacoes.php" id="savedTabulationsNav" hidden><span class="nav-icon">▧</span>Minhas Tabulações</a>
      </nav>
      <div class="sidebar-foot">
        <span class="source-dot"></span>
        <div><strong>Fonte oficial</strong><small>DATASUS · HTTPS / FTP</small></div>
        <span class="sidebar-version">v<?= htmlspecialchars(tabwin2_app_version(), ENT_QUOTES, 'UTF-8') ?></span>
      </div>
    </aside>

    <main class="main-content location-main" id="busca">
      <header class="topbar"><div class="breadcrumb">Dados públicos <span>/</span> <strong id="pageBreadcrumb">Início</strong></div><div class="top-tag" id="locationTag"><span></span><b>Escolha a UF</b></div></header>
      <section class="intro" id="pageIntro">
        <div class="eyebrow"><span class="eyebrow-line"></span> DADOS PÚBLICOS DE SAÚDE</div>
        <h1>Comece pela<br class="mobile-break"> localidade.</h1>
        <p>Escolha o estado dos dados. Se quiser, defina também um município para recortar a tabulação quando o relatório oferecer esse campo.</p>
      </section>

      <nav class="search-progress" aria-label="Etapas de acesso aos dados">
        <div class="search-progress-step active" id="progressLocation" aria-current="step"><span>01</span><div><strong>Localidade</strong><small>Estado e recorte opcional</small></div></div>
        <i aria-hidden="true"></i>
        <div class="search-progress-step" id="progressFiles"><span>02</span><div><strong id="nextStepTitle">Tabulações prontas</strong><small id="nextStepHint">Relatórios disponíveis</small></div></div>
      </nav>

      <section class="location-step-screen" id="locationStep" aria-label="Escolha da localidade">
        <section class="location-picker" aria-labelledby="locationHeading">
          <div class="map-panel">
            <div class="location-panel-heading"><div><span class="location-step">BRASIL · 27 UNIDADES DA FEDERAÇÃO</span><h3 id="locationHeading">Selecione um estado</h3></div><div class="map-panel-utility"><span class="tile-motif" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span><span class="map-credit">Mapa · IBGE</span></div></div>
            <div class="map-frame" id="mapMount" aria-busy="true"><div class="map-placeholder" role="status">Carregando mapa do Brasil…</div></div>
            <div class="map-caption"><span class="map-key"><i></i><span id="mapKeyText">Selecione uma UF</span></span><span id="mapTooltip" aria-live="polite">Passe o cursor ou use o teclado</span></div>
          </div>
          <div class="location-controls">
            <div class="location-copy"><div class="location-copy-kicker"><span class="tile-motif" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span><span class="location-kicker">ETAPA 01 · LOCALIDADE</span></div><h2>Onde estão os dados?</h2><p class="location-intro">Os arquivos do DATASUS são estaduais. O município é opcional; o filtro será aplicado quando o relatório tiver um campo municipal compatível.</p></div>
            <label class="field"><span>ESTADO / UNIDADE DA FEDERAÇÃO</span><select id="uf"><option value="">Selecione um estado…</option><option value="AC">Acre · AC</option><option value="AL">Alagoas · AL</option><option value="AP">Amapá · AP</option><option value="AM">Amazonas · AM</option><option value="BA">Bahia · BA</option><option value="CE">Ceará · CE</option><option value="DF">Distrito Federal · DF</option><option value="ES">Espírito Santo · ES</option><option value="GO">Goiás · GO</option><option value="MA">Maranhão · MA</option><option value="MT">Mato Grosso · MT</option><option value="MS">Mato Grosso do Sul · MS</option><option value="MG">Minas Gerais · MG</option><option value="PA">Pará · PA</option><option value="PB">Paraíba · PB</option><option value="PR">Paraná · PR</option><option value="PE">Pernambuco · PE</option><option value="PI">Piauí · PI</option><option value="RJ">Rio de Janeiro · RJ</option><option value="RN">Rio Grande do Norte · RN</option><option value="RS">Rio Grande do Sul · RS</option><option value="RO">Rondônia · RO</option><option value="RR">Roraima · RR</option><option value="SC">Santa Catarina · SC</option><option value="SP">São Paulo · SP</option><option value="SE">Sergipe · SE</option><option value="TO">Tocantins · TO</option></select></label>
            <div class="municipality-picker"><label class="field"><span>RECORTE MUNICIPAL · OPCIONAL</span><input id="municipalitySearch" type="search" aria-label="Localizar município" placeholder="Localizar município" autocomplete="off" disabled></label><label class="field municipality-select-field"><span class="sr-only">Selecionar município</span><select id="municipality" aria-label="Selecionar município para a tabulação" disabled><option value="">Escolha primeiro um estado…</option></select></label></div>
            <div class="location-hint" id="locationHint" role="status">Escolha uma UF no mapa ou na lista para continuar.</div>
            <button class="button button-primary location-continue" id="advanceToFiles" type="button" disabled>Ver tabulações prontas <span aria-hidden="true">→</span></button>
          </div>
        </section>
      </section>

      <section class="workspace" id="filesStep" aria-label="Seleção de arquivos DATASUS" hidden>
        <div class="files-step-heading"><div class="step-heading"><span class="step-number">02</span><div><h2>Selecione os arquivos</h2><p>Escolha a base, o ano e a competência para consultar o DATASUS.</p></div><span class="source-status"><span class="source-dot"></span> Fonte oficial</span></div><button class="button-secondary change-state" id="changeStateButton" type="button"><span aria-hidden="true">←</span> Trocar estado</button></div>
        <div class="filters">
          <label class="field field-system"><span>BASE DE DADOS</span><select id="system"><option value="sia">Ambulatorial · SIA/SUS</option><option value="sih">Hospitalar · SIH/SUS</option></select></label>
          <label class="field"><span>ANO</span><select id="year"></select></label>
          <label class="field"><span>COMPETÊNCIA</span><select id="month" disabled><option value="">Buscando períodos…</option></select></label>
          <button class="button button-primary" id="searchButton" type="button"><span class="search-glyph">⌕</span> Buscar arquivos</button>
        </div>
        <div class="scope-note"><span class="info-icon">i</span><span id="scopeCopy">A lista acompanha o estado escolhido. O município selecionado poderá ser aplicado à tabulação quando o relatório tiver um campo municipal compatível; isso não altera a abrangência do arquivo DBC.</span></div>

        <div class="results" id="results" aria-live="polite">
          <div class="empty-state" id="emptyState">
            <div class="search-loader" id="searchLoader" aria-hidden="true" hidden><span></span><span></span><span></span><span></span><span></span></div>
            <div class="empty-icon" id="emptyIcon"><span>⌕</span></div>
            <strong id="emptyTitle">Escolha uma localidade</strong>
            <p id="emptyCopy">Selecione uma UF no mapa ou na lista para consultar os arquivos estaduais.</p>
          </div>
          <div class="query-progress" id="queryProgress" hidden aria-live="polite">
            <div class="query-progress-meta"><span id="queryProgressStage">Preparando consulta</span><span id="queryProgressPercent">0%</span></div>
            <div class="query-progress-track" id="queryProgressTrack" role="progressbar" aria-label="Andamento estimado da consulta" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" aria-valuetext="Estimativa visual enquanto a fonte responde"><span id="queryProgressFill"></span></div>
          </div>
          <div class="results-content" id="resultsContent" hidden>
            <div class="results-head"><div><div class="results-title"><h3>Arquivos encontrados</h3><span class="count-badge" id="fileCount">0</span></div><p id="resultsSummary">Selecione os arquivos que deseja importar.</p></div><button class="text-button" id="selectAll" type="button">Selecionar todos</button></div>
            <div class="file-table-wrap"><table class="file-table"><thead><tr><th class="check-column"><span class="sr-only">Selecionar</span></th><th>ARQUIVO / CONTEÚDO</th><th>FAMÍLIA</th><th>TAMANHO</th><th>STATUS</th><th>MODIFICADO</th><th class="file-action-heading">AÇÃO</th></tr></thead><tbody id="fileRows"></tbody></table></div>
            <div class="download-bar"><div class="selection-summary"><span class="selection-mark">✓</span><span><strong id="selectedCount">0 arquivos selecionados</strong><small id="selectedSize">Escolha um ou mais arquivos para continuar</small></span></div><button class="button button-primary" id="downloadButton" type="button" disabled>Adicionar à biblioteca <span aria-hidden="true">→</span></button></div>
          </div>
          <div class="notice" id="notice" hidden role="status"></div>
        </div>
        <section class="library-card">
          <div class="library-icon">▤</div><div class="library-copy"><strong>Uma biblioteca organizada, pronta para tabular</strong><p>Os arquivos ficam separados por sistema, ano, competência e tipo. Na próxima etapa, vamos cruzá-los com os arquivos de definição compatíveis com o TabWin.</p></div><div class="library-path"><span>ARQUIVOS LOCAIS</span><code>SPPtab / biblioteca</code></div>
        </section>
      </section>

      <footer class="page-footer"><span>SPPtab <span class="footer-separator">·</span> <span id="pageStepLabel">escolha da localidade</span></span><span>Dados públicos do Ministério da Saúde / DATASUS</span></footer>
    </main>
  </div>
  <script src="assets/app.js?v=23" defer></script>
  <script src="assets/tabulations-nav.js?v=1" defer></script>
  <script src="assets/launch-splash.js?v=3" defer></script>
</body>
</html>
