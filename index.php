<?php
declare(strict_types=1);
?><!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#f4f7f8">
  <title>SPPtab · DATASUS</title>
  <link rel="stylesheet" href="assets/app.css?v=2">
  <link rel="stylesheet" href="assets/brand.css?v=1">
  <link rel="stylesheet" href="assets/launch.css?v=2">
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
  <div class="app-shell">
    <aside class="sidebar">
      <a class="brand" href="./" aria-label="SPPtab, início">
        <span class="brand-mark" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span></span>
        <span><strong>SPPtab</strong><small>saúde em dados</small></span>
      </a>
      <div class="nav-label">ESPAÇO DE TRABALHO</div>
      <nav aria-label="Navegação principal">
        <a class="nav-item active" href="#busca"><span class="nav-icon">⌕</span>Buscar arquivos</a>
        <a class="nav-item" href="tabular.php"><span class="nav-icon">▦</span>Minhas bases</a>
        <a class="nav-item" href="tabular.php"><span class="nav-icon">▤</span>Tabular dados</a>
      </nav>
      <div class="sidebar-foot">
        <span class="source-dot"></span>
        <div><strong>Fonte oficial</strong><small>DATASUS · HTTPS / FTP</small></div>
      </div>
    </aside>

    <main class="main-content" id="busca">
      <header class="topbar"><div class="breadcrumb">Dados públicos <span>/</span> <strong>Busca de arquivos</strong></div><div class="top-tag"><span></span> PARÁ · PA</div></header>
      <section class="intro">
        <div class="eyebrow"><span class="eyebrow-line"></span> IMPORTAÇÃO DE DADOS</div>
        <h1>Encontre a base<br class="mobile-break"> que você precisa.</h1>
        <p>Consulte as competências disponíveis no DATASUS e traga os arquivos para uma biblioteca organizada, prontos para a próxima etapa de leitura.</p>
      </section>

      <section class="workspace" aria-label="Busca de arquivos DATASUS">
        <div class="step-heading"><span class="step-number">01</span><div><h2>Escolha a competência</h2><p>Os arquivos são publicados por estado e mês.</p></div><span class="source-status"><span class="source-dot"></span> Consulta ao DATASUS</span></div>
        <div class="filters">
          <label class="field field-system"><span>BASE DE DADOS</span><select id="system"><option value="sia">Ambulatorial · SIA/SUS</option><option value="sih">Hospitalar · SIH/SUS</option></select></label>
          <label class="field"><span>ANO</span><select id="year"></select></label>
          <label class="field"><span>COMPETÊNCIA</span><select id="month" disabled><option value="">Buscando períodos…</option></select></label>
          <button class="button button-primary" id="searchButton" type="button"><span class="search-glyph">⌕</span> Buscar arquivos</button>
        </div>
        <div class="scope-note"><span class="info-icon">i</span><span>Os dados são do <strong>estado do Pará</strong>. Belém será aplicado como filtro municipal na tabulação, usando o código IBGE <strong>150140</strong>.</span></div>

        <div class="results" id="results" aria-live="polite">
          <div class="empty-state" id="emptyState">
            <div class="empty-icon"><span>⌕</span></div>
            <strong id="emptyTitle">Consultando competências</strong>
            <p id="emptyCopy">Estamos verificando quais meses já foram publicados para esta base.</p>
          </div>
          <div class="results-content" id="resultsContent" hidden>
            <div class="results-head"><div><div class="results-title"><h3>Arquivos encontrados</h3><span class="count-badge" id="fileCount">0</span></div><p id="resultsSummary">Selecione os arquivos que deseja importar.</p></div><button class="text-button" id="selectAll" type="button">Selecionar todos</button></div>
            <div class="file-table-wrap"><table class="file-table"><thead><tr><th class="check-column"><span class="sr-only">Selecionar</span></th><th>ARQUIVO / CONTEÚDO</th><th>FAMÍLIA</th><th>TAMANHO</th><th>STATUS</th><th>MODIFICADO</th></tr></thead><tbody id="fileRows"></tbody></table></div>
            <div class="download-bar"><div class="selection-summary"><span class="selection-mark">✓</span><span><strong id="selectedCount">0 arquivos selecionados</strong><small id="selectedSize">Escolha um ou mais arquivos para continuar</small></span></div><button class="button button-primary" id="downloadButton" type="button" disabled>Adicionar à biblioteca <span aria-hidden="true">→</span></button></div>
          </div>
          <div class="notice" id="notice" hidden role="status"></div>
        </div>
      </section>

      <section class="library-card">
        <div class="library-icon">▤</div><div class="library-copy"><strong>Uma biblioteca organizada, pronta para tabular</strong><p>Os arquivos ficam separados por sistema, ano, competência e tipo. Na próxima etapa, vamos cruzá-los com os arquivos de definição compatíveis com o TabWin.</p></div><div class="library-path"><span>ARQUIVOS LOCAIS</span><code>SPPtab / biblioteca</code></div>
      </section>

      <footer class="page-footer"><span>SPPtab <span class="footer-separator">·</span> etapa 1 de 3</span><span>Dados públicos do Ministério da Saúde / DATASUS</span></footer>
    </main>
  </div>
  <script src="assets/app.js?v=2" defer></script>
  <script src="assets/launch-splash.js?v=2" defer></script>
</body>
</html>
