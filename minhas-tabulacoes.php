<?php declare(strict_types=1); ?><!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#f4f7f8">
  <title>Minhas Tabulações · SPPtab</title>
  <link rel="stylesheet" href="assets/app.css?v=14"><link rel="stylesheet" href="assets/brand.css?v=1"><link rel="stylesheet" href="assets/tabular-refine.css?v=18"><link rel="stylesheet" href="assets/presets.css?v=1">
</head>
<body>
  <div class="app-shell">
    <aside class="sidebar">
      <a class="brand" href="./" aria-label="SPPtab, início"><span class="brand-mark" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span></span><span><strong>SPPtab</strong><small>saúde em dados</small></span></a>
      <div class="nav-label">ESPAÇO DE TRABALHO</div>
<nav aria-label="Navegação principal"><a class="nav-item" href="index.php"><span class="nav-icon">⌕</span>Buscar arquivos</a><a class="nav-item" href="bases.php"><span class="nav-icon">▦</span>Minhas bases</a><a class="nav-item" href="tabular.php"><span class="nav-icon">▤</span>Tabular dados</a><a class="nav-item active" id="savedTabulationsNav" href="minhas-tabulacoes.php" aria-current="page" hidden><span class="nav-icon">▧</span>Minhas Tabulações</a></nav>
      <div class="sidebar-foot"><span class="source-dot"></span><div><strong>Modelos locais</strong><small>Salvos neste computador</small></div></div>
    </aside>
    <main class="main-content presets-main">
      <header class="topbar"><div class="breadcrumb">Dados públicos <span>/</span> <strong>Minhas Tabulações</strong></div><div class="top-tag"><span></span><b id="selectedFileTag">Selecione um arquivo</b></div></header>
      <section class="intro presets-intro"><div class="eyebrow"><span class="eyebrow-line"></span> COMBINAÇÕES REUTILIZÁVEIS</div><h1>Minhas Tabulações</h1><p>Salve uma configuração uma vez e aplique em outras competências com a mesma estrutura e definição oficial.</p></section>

      <section class="workspace preset-context-card" aria-labelledby="presetSourceTitle">
        <div class="preset-context-heading"><span class="preset-heading-mark" aria-hidden="true"><span class="tile-motif"><i></i><i></i><i></i><i></i><i></i></span></span><div><h2 id="presetSourceTitle">Escolha o arquivo de referência</h2><p>As combinações aparecem quando a estrutura da base é compatível.</p></div></div>
        <div class="preset-context-controls"><label class="field"><span>DBC SELECIONADO</span><select id="presetSource"><option value="">Carregando biblioteca…</option></select></label><div class="preset-context-info" id="presetSourceInfo" role="status">Localizando o arquivo selecionado…</div></div>
      </section>

      <section class="workspace preset-list-card" aria-labelledby="presetsTitle">
        <div class="preset-list-head"><div><div class="preset-list-title"><span class="tile-motif" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span><h2 id="presetsTitle">Combinações salvas</h2><span class="count-badge" id="presetCount">0</span></div><p id="presetListDescription">Selecione um arquivo para ver os modelos compatíveis.</p></div><a class="text-button" id="createPresetLink" href="tabular.php" hidden>Salvar uma combinação <span aria-hidden="true">↗</span></a></div>
        <div class="preset-list-state" id="presetLoading" role="status" aria-live="polite"><span class="tile-motif tile-motif--large" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span><strong>Consultando combinações</strong><span>Conferindo a estrutura e a definição oficial…</span></div>
        <div class="preset-cards" id="presetCards"></div>
        <div class="preset-list-state preset-empty" id="presetEmpty" hidden><span class="preset-empty-mark" aria-hidden="true"><span class="tile-motif"><i></i><i></i><i></i><i></i><i></i></span></span><strong id="presetEmptyTitle">Nenhuma combinação salva</strong><span id="presetEmptyCopy">Monte uma tabulação e salve as opções para reutilizar em outra competência.</span><a class="button button-primary" id="presetEmptyAction" href="tabular.php">Ir para tabular dados <span aria-hidden="true">→</span></a></div>
        <div class="preset-notice" id="presetPageNotice" role="status" aria-live="polite" hidden></div>
      </section>
      <footer class="page-footer"><span>SPPtab <span class="footer-separator">·</span> modelos guardados neste computador</span><span>A competência e a localidade não ficam salvas na combinação</span></footer>
    </main>
  </div>
  <script src="assets/tabulations-nav.js?v=1" defer></script><script src="assets/saved-tabulations.js?v=4" defer></script>
</body>
</html>
