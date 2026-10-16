<?php declare(strict_types=1); ?><!doctype html>
<html lang="pt-BR"><head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#f4f7f8">
  <title>Pacotes de dados · SPPtab</title>
  <link rel="stylesheet" href="assets/app.css?v=12"><link rel="stylesheet" href="assets/brand.css?v=1"><link rel="stylesheet" href="assets/tabular-refine.css?v=17"><link rel="stylesheet" href="assets/packages.css?v=1">
</head><body><div class="app-shell">
  <aside class="sidebar">
    <a class="brand" href="./" aria-label="SPPtab, início"><span class="brand-mark" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span></span><span><strong>SPPtab</strong><small>saúde em dados</small></span></a>
    <div class="nav-label">ESPAÇO DE TRABALHO</div>
    <nav aria-label="Navegação principal"><a class="nav-item" href="index.php"><span class="nav-icon">⌕</span>Buscar arquivos</a><a class="nav-item" href="bases.php"><span class="nav-icon">▦</span>Minhas bases</a><a class="nav-item" href="tabular.php"><span class="nav-icon">▤</span>Tabular dados</a><a class="nav-item active" href="pacotes.php" aria-current="page"><span class="nav-icon">▧</span>Pacotes de dados</a><a class="nav-item" id="savedTabulationsNav" href="minhas-tabulacoes.php" hidden><span class="nav-icon">▧</span>Minhas Tabulações</a></nav>
    <div class="sidebar-foot"><span class="source-dot"></span><div><strong>Fontes oficiais</strong><small>CNES · DATASUS</small></div></div>
  </aside>
  <main class="main-content packages-main">
    <header class="topbar"><div class="breadcrumb">Dados públicos <span>/</span> <strong>Pacotes de dados</strong></div><div class="top-tag" id="packageLocationTag"><span></span><b>Escolha a UF</b></div></header>
    <section class="intro packages-intro"><div class="eyebrow"><span class="eyebrow-line"></span> BASES COMPLEMENTARES</div><h1>Pacotes de dados</h1><p>Baixe módulos do CNES — estabelecimentos, profissionais, leitos e outros — e a tabela de procedimentos SIGTAP. Depois, cruze os códigos com a tabulação ambulatorial ou hospitalar.</p></section>

    <section class="workspace package-picker" aria-labelledby="packagePickerTitle">
      <div class="package-section-heading"><div class="package-heading-mark"><span class="tile-motif" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span></div><div><span class="package-step">01 · RECORTE</span><h2 id="packagePickerTitle">Escolha a localidade e a competência</h2><p>As listas são consultadas nas fontes públicas do CNES e do SIGTAP.</p></div><button class="package-refresh" id="refreshCatalog" type="button" title="Atualizar a lista no DATASUS" aria-label="Atualizar lista">↻</button></div>
      <div class="package-controls">
        <label class="field"><span>ESTADO</span><select id="packageUf"><option value="PA">Pará · PA</option></select></label>
        <label class="field"><span>ANO</span><select id="packageYear" disabled><option>Carregando…</option></select></label>
        <label class="field"><span>COMPETÊNCIA</span><select id="packageMonth" disabled><option>Carregando…</option></select></label>
      </div>
      <div class="package-source-note"><span class="source-dot"></span><span id="catalogStatus" role="status" aria-live="polite">Consultando arquivos publicados pelo CNES…</span></div>
      <div class="package-cards" id="packageCards" aria-live="polite"></div>
      <div class="package-action-row"><span id="packageSelectionInfo">Selecione os módulos que deseja manter no computador.</span><button class="button button-primary" id="downloadPackages" type="button" disabled>Baixar pacotes selecionados <span aria-hidden="true">↓</span></button></div>
      <section class="package-progress" id="packageProgress" hidden aria-live="polite">
        <div class="progress-meta"><strong id="packageProgressStage">Preparando pacotes</strong><span id="packageProgressPercent">0%</span></div>
        <div class="progress-track" role="progressbar" aria-label="Progresso de preparação dos pacotes CNES" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><span id="packageProgressFill"></span></div>
        <small id="packageProgressCopy">A transferência e a conversão serão acompanhadas aqui.</small>
      </section>
      <div class="package-notice" id="packageNotice" role="status" aria-live="polite" hidden></div>
    </section>

    <section class="package-library" aria-labelledby="packageLibraryTitle">
      <div class="package-library-head"><div><span class="package-step">02 · BIBLIOTECA LOCAL</span><h2 id="packageLibraryTitle">Pacotes prontos para cruzamento</h2><p>Arquivos convertidos ficam neste computador e podem ser reutilizados nas próximas consultas.</p></div><span class="package-library-count" id="packageLibraryCount">—</span></div>
      <div class="package-local-grid" id="packageLocalGrid"><div class="package-library-loading" role="status"><span class="tile-motif tile-motif--large" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span>Carregando pacotes locais…</div></div>
    </section>

    <section class="package-cross-note"><span class="package-cross-icon" aria-hidden="true">↔</span><div><strong>Cruze a partir do resultado da tabulação</strong><p>Gere a consulta SIA/SIH primeiro. Na aba do resultado, escolha um pacote compatível e relacione o código da linha com CNES, CNS profissional ou procedimento.</p></div><a class="text-button" href="tabular.php">Ir para tabulação <span aria-hidden="true">→</span></a></section>
    <footer class="page-footer"><span>SPPtab <span class="footer-separator">·</span> dados complementares</span><span>Fontes: DATASUS · CNES e SIGTAP</span></footer>
  </main>
</div><script src="assets/packages.js?v=1" defer></script><script src="assets/tabulations-nav.js?v=1" defer></script></body></html>
