<?php declare(strict_types=1); ?><!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#f4f7f8">
  <title>Minhas bases · SPPtab</title>
  <link rel="stylesheet" href="assets/app.css?v=12"><link rel="stylesheet" href="assets/brand.css?v=1"><link rel="stylesheet" href="assets/tabular-refine.css?v=11"><link rel="stylesheet" href="assets/bases.css?v=2">
</head>
<body>
  <div class="app-shell">
    <aside class="sidebar">
      <a class="brand" href="./" aria-label="SPPtab, início"><span class="brand-mark" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span></span><span><strong>SPPtab</strong><small>saúde em dados</small></span></a>
      <div class="nav-label">ESPAÇO DE TRABALHO</div>
      <nav aria-label="Navegação principal"><a class="nav-item" href="index.php"><span class="nav-icon">⌕</span>Buscar arquivos</a><a class="nav-item active" href="bases.php" aria-current="page"><span class="nav-icon">▦</span>Minhas bases</a><a class="nav-item" href="tabular.php"><span class="nav-icon">▤</span>Tabular dados</a><a class="nav-item" href="pacotes.php"><span class="nav-icon">▧</span>Pacotes de dados</a><a class="nav-item" id="savedTabulationsNav" href="minhas-tabulacoes.php" hidden><span class="nav-icon">▧</span>Minhas Tabulações</a></nav>
      <div class="sidebar-foot"><span class="source-dot"></span><div><strong>Biblioteca local</strong><small>Arquivos deste computador</small></div></div>
    </aside>
    <main class="main-content bases-main">
      <header class="topbar"><div class="breadcrumb">Dados públicos <span>/</span> <strong>Minhas bases</strong></div><div class="top-tag"><span></span><b id="libraryCountTag">Biblioteca local</b></div></header>
      <section class="intro bases-intro"><div class="eyebrow"><span class="eyebrow-line"></span> BIBLIOTECA LOCAL</div><h1>Minhas bases</h1><p>Gerencie os arquivos ambulatoriais e hospitalares que você adicionou. Bases convertidas já estão prontas para tabular.</p></section>

      <section class="bases-summary" aria-label="Resumo da biblioteca">
        <article class="bases-stat"><div class="bases-stat-icon"><span class="tile-motif" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span></div><div><span>ARQUIVOS NA BIBLIOTECA</span><strong id="totalCount">—</strong><small>Arquivos DBC importados</small></div></article>
        <article class="bases-stat"><div class="bases-stat-icon bases-stat-icon--soft">SIA</div><div><span>AMBULATORIAL</span><strong id="siaCount">—</strong><small>SIA/SUS</small></div></article>
        <article class="bases-stat"><div class="bases-stat-icon bases-stat-icon--soft">SIH</div><div><span>HOSPITALAR</span><strong id="sihCount">—</strong><small>SIH/SUS</small></div></article>
        <article class="bases-stat"><div class="bases-stat-icon bases-stat-icon--ready">✓</div><div><span>PRONTAS PARA TABULAR</span><strong id="convertedCount">—</strong><small>DBF convertido disponível</small></div></article>
      </section>

      <section class="workspace bases-library" aria-labelledby="libraryTitle">
        <div class="bases-library-head"><div class="bases-title-group"><span class="bases-heading-icon" aria-hidden="true"><span class="tile-motif" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span></span><div><h2 id="libraryTitle">Arquivos importados</h2><p>Organizados por sistema, estado e competência.</p></div></div><a class="button button-primary" href="index.php"><span aria-hidden="true">＋</span> Adicionar arquivos</a></div>
        <div class="bases-toolbar">
          <label class="bases-search"><span class="sr-only">Buscar arquivos na biblioteca</span><span aria-hidden="true">⌕</span><input id="librarySearch" type="search" placeholder="Buscar arquivo, estado ou competência" autocomplete="off"></label>
          <label class="bases-filter"><span class="sr-only">Filtrar sistema</span><select id="systemFilter"><option value="all">Todos os sistemas</option><option value="SIA">Ambulatorial · SIA/SUS</option><option value="SIH">Hospitalar · SIH/SUS</option></select></label>
          <span class="bases-visible-count" id="visibleCount" aria-live="polite">Carregando arquivos…</span>
        </div>
        <div class="bases-table-wrap">
          <table class="bases-table"><thead><tr><th>ARQUIVO / COMPETÊNCIA</th><th>SISTEMA</th><th>ESTADO</th><th>TAMANHO</th><th>CONVERSÃO</th><th class="bases-actions-heading">AÇÕES</th></tr></thead><tbody id="libraryRows"></tbody></table>
          <div class="bases-loading" id="libraryLoading" role="status" aria-live="polite"><span class="tile-motif tile-motif--large" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span><strong>Carregando sua biblioteca</strong><span>Localizando os arquivos deste computador…</span></div>
          <div class="bases-empty" id="libraryEmpty" hidden><span class="bases-empty-mark" aria-hidden="true"><span class="tile-motif" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span></span><strong id="emptyTitle">Sua biblioteca ainda está vazia</strong><p id="emptyCopy">Adicione arquivos DBC ambulatoriais ou hospitalares para começar a organizar suas bases.</p><a class="button button-primary" href="index.php">Buscar arquivos</a></div>
        </div>
        <div class="bases-footnote"><span class="bases-info-mark" aria-hidden="true">i</span><span>Remover um arquivo exclui o DBC e, se existir, o DBF convertido deste computador.</span></div>
        <div class="bases-notice" id="libraryNotice" role="status" aria-live="polite" hidden></div>
      </section>
      <footer class="page-footer"><span>SPPtab <span class="footer-separator">·</span> biblioteca local</span><span>Dados públicos do Ministério da Saúde / DATASUS</span></footer>
    </main>
  </div>

  <dialog class="remove-dialog" id="removeDialog" aria-labelledby="removeTitle" aria-describedby="removeCopy">
    <div class="remove-dialog-mark" aria-hidden="true"><span>×</span></div>
    <h2 id="removeTitle">Remover arquivo da biblioteca?</h2>
    <p id="removeCopy">O arquivo original e o DBF convertido serão excluídos deste computador.</p>
    <div class="remove-file-name" id="removeFileName"></div>
    <div class="remove-dialog-error" id="removeError" role="alert" hidden></div>
    <div class="remove-dialog-actions"><button class="button-secondary" id="cancelRemove" type="button">Manter arquivo</button><button class="button remove-confirm" id="confirmRemove" type="button">Remover arquivo</button></div>
  </dialog>
      <script src="assets/bases.js?v=3" defer></script><script src="assets/tabulations-nav.js?v=1" defer></script>
</body>
</html>
