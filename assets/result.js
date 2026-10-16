(() => {
  'use strict';
  const $ = (selector) => document.querySelector(selector);
  const params = new URLSearchParams(location.search);
  const runId = params.get('run');
  const MAX_FILTER_OPTIONS = 250;
  let result = null;
  let activeFilterMenu = null;
  let filterState = new Map();
  let pendingAdditionalColumns = new Set();
  let pendingMainColumn = '';
  let isUpdatingColumns = false;

  const fmt = (value) => {
    const number = Number(value);
    return Number.isFinite(number) ? number.toLocaleString('pt-BR', { maximumFractionDigits: 4 }) : String(value ?? '');
  };
  const numeric = (value) => {
    const number = Number(String(value ?? '').replace(',', '.'));
    return Number.isFinite(number) ? number : 0;
  };

  function showError(message) {
    if (result) return;
    $('#resultTitle').textContent = 'Não foi possível abrir o resultado';
    $('#resultSummary').textContent = message;
    $('#resultStatus').textContent = 'Volte à tela de tabulação e tente novamente.';
    $('#resultStatus').classList.add('error');
  }

  function valueFor(row, key) {
    if (key === 'row') return String(row.label ?? '');
    if (key === 'rowtotal') return String(row.total ?? '');
    const match = /^value:(\d+)$/.exec(key);
    return match ? String(row.values?.[Number(match[1])] ?? '') : '';
  }

  function distinctValuesFor(data, key) {
    return [...new Set((data.rows || []).map((row) => valueFor(row, key)))].sort((a, b) =>
      a.localeCompare(b, 'pt-BR', { numeric: true, sensitivity: 'base' }),
    );
  }

  function activeFilterCount() {
    return [...filterState.values()].filter((selected) => selected !== null).length;
  }

  function visibleRows() {
    const rows = result?.rows || [];
    if (!filterState.size) return rows;
    return rows.filter((row) => {
      for (const [key, selected] of filterState) {
        if (selected !== null && !selected.has(valueFor(row, key))) return false;
      }
      return true;
    });
  }

  function updateFilterSummary(rows) {
    const total = result?.rows?.length || 0;
    const active = activeFilterCount();
    $('#visibleSummary').textContent = active
      ? `${fmt(rows.length)} de ${fmt(total)} linhas · ${active} ${active === 1 ? 'filtro ativo' : 'filtros ativos'}`
      : `${fmt(total)} ${total === 1 ? 'linha exibida' : 'linhas exibidas'}`;
  }

  function renderVisibleTable() {
    if (!result) return;
    const rows = visibleRows();
    const body = $('#resultBody');
    const foot = $('#resultFoot');
    const columns = result.columns || [];
    const showRowTotal = (result.metrics || []).length === 1 && (columns.length > 1 || columns[0] !== 'Total');
    const filtered = activeFilterCount() > 0;
    body.replaceChildren();
    foot.replaceChildren();

    rows.forEach((row) => {
      const tr = document.createElement('tr');
      const label = document.createElement('td');
      label.className = 'result-label';
      const name = document.createElement('span');
      name.textContent = row.label;
      label.append(name);
      if (row.key) {
        const key = document.createElement('small');
        key.className = 'result-key';
        key.textContent = `código ${row.key}`;
        label.append(key);
      }
      if (row.unclassified) label.classList.add('unclassified-row');
      tr.append(label);

      (row.values || []).forEach((value) => {
        const td = document.createElement('td');
        td.textContent = fmt(value);
        tr.append(td);
      });
      if (showRowTotal) {
        const td = document.createElement('td');
        td.className = 'row-total';
        td.textContent = fmt((row.values || []).reduce((sum, value) => sum + numeric(value), 0));
        tr.append(td);
      }
      body.append(tr);
    });

    const totals = columns.map((_, index) => filtered
      ? rows.reduce((sum, row) => sum + numeric(row.values?.[index]), 0)
      : numeric(result.columnTotals?.[index]));
    const totalRow = document.createElement('tr');
    const totalLabel = document.createElement('th');
    totalLabel.textContent = 'Total geral';
    totalRow.append(totalLabel);
    totals.forEach((value) => {
      const td = document.createElement('td');
      td.textContent = fmt(value);
      totalRow.append(td);
    });
    if (showRowTotal) {
      const td = document.createElement('td');
      const total = filtered
        ? totals.reduce((sum, value) => sum + value, 0)
        : numeric(result.total);
      td.textContent = fmt(total);
      totalRow.append(td);
    }
    foot.append(totalRow);

    updateFilterSummary(rows);
    updateFilterTriggerStates();
  }

  function closeFilterMenu() {
    if (!activeFilterMenu) return;
    activeFilterMenu.trigger.setAttribute('aria-expanded', 'false');
    activeFilterMenu.menu.remove();
    activeFilterMenu = null;
  }

  function updateFilterTriggerStates() {
    document.querySelectorAll('.result-filter-trigger').forEach((button) => {
      const selected = filterState.get(button.dataset.filterKey);
      const isFiltered = selected !== undefined && selected !== null;
      button.classList.toggle('is-active', isFiltered);
      button.setAttribute('aria-label', `${isFiltered ? 'Filtro ativo em' : 'Filtrar'} ${button.dataset.filterLabel}`);
    });
  }

  function setFilter(key, selected) {
    const all = distinctValuesFor(result, key);
    if (selected === null || selected.size >= all.length) filterState.delete(key);
    else filterState.set(key, selected);
    renderVisibleTable();
    if (activeFilterMenu?.key === key) renderFilterMenuOptions(activeFilterMenu);
  }

  function renderFilterMenuOptions(state) {
    const all = distinctValuesFor(result, state.key);
    const selected = filterState.get(state.key);
    const query = state.search.value.trim().toLocaleLowerCase('pt-BR');
    const matches = query ? all.filter((value) => value.toLocaleLowerCase('pt-BR').includes(query)) : all;
    const shown = matches.slice(0, MAX_FILTER_OPTIONS);
    state.count.textContent = selected === undefined || selected === null
      ? `${fmt(all.length)} valores · todos incluídos`
      : `${fmt(selected.size)} de ${fmt(all.length)} valores incluídos`;
    state.list.replaceChildren();

    if (!shown.length) {
      const empty = document.createElement('p');
      empty.className = 'result-filter-empty';
      empty.textContent = 'Nenhum valor encontrado.';
      state.list.append(empty);
    } else {
      shown.forEach((value) => {
        const label = document.createElement('label');
        label.className = 'result-filter-option';
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.checked = selected === undefined || selected === null || selected.has(value);
        const copy = document.createElement('span');
        copy.textContent = state.key === 'row' ? value : fmt(value);
        copy.title = copy.textContent;
        label.append(checkbox, copy);
        checkbox.addEventListener('change', () => {
          const next = selected === undefined || selected === null ? new Set(all) : new Set(selected);
          if (checkbox.checked) next.add(value);
          else next.delete(value);
          setFilter(state.key, next);
        });
        state.list.append(label);
      });
    }

    state.limit.hidden = matches.length <= MAX_FILTER_OPTIONS;
    state.limit.textContent = query
      ? `Mostrando os primeiros ${MAX_FILTER_OPTIONS} resultados da busca.`
      : `Há ${fmt(all.length)} valores. Pesquise para localizar um valor específico.`;
  }

  function openFilterMenu(key, label, trigger) {
    if (activeFilterMenu?.trigger === trigger) {
      closeFilterMenu();
      return;
    }
    closeFilterMenu();

    const menu = document.createElement('div');
    menu.className = 'result-filter-menu';
    menu.setAttribute('role', 'dialog');
    menu.setAttribute('aria-label', `Filtrar ${label}`);
    const heading = document.createElement('div');
    heading.className = 'result-filter-menu__heading';
    heading.textContent = `Filtrar: ${label}`;
    const search = document.createElement('input');
    search.className = 'result-filter-search';
    search.type = 'search';
    search.placeholder = 'Pesquisar valores';
    search.setAttribute('aria-label', `Pesquisar valores em ${label}`);
    const actions = document.createElement('div');
    actions.className = 'result-filter-menu__actions';
    const allButton = document.createElement('button');
    allButton.type = 'button';
    allButton.textContent = 'Selecionar todos';
    const noneButton = document.createElement('button');
    noneButton.type = 'button';
    noneButton.textContent = 'Limpar seleção';
    actions.append(allButton, noneButton);
    const count = document.createElement('div');
    count.className = 'result-filter-count';
    const list = document.createElement('div');
    list.className = 'result-filter-list';
    const limit = document.createElement('p');
    limit.className = 'result-filter-limit';
    menu.append(heading, search, actions, count, list, limit);
    document.body.append(menu);

    const state = { key, trigger, menu, search, count, list, limit };
    activeFilterMenu = state;
    trigger.setAttribute('aria-expanded', 'true');
    const rect = trigger.getBoundingClientRect();
    const menuWidth = Math.min(310, window.innerWidth - 20);
    menu.style.width = `${menuWidth}px`;
    menu.style.left = `${Math.max(10, Math.min(rect.right - menuWidth, window.innerWidth - menuWidth - 10))}px`;

    allButton.addEventListener('click', () => setFilter(key, null));
    noneButton.addEventListener('click', () => setFilter(key, new Set()));
    search.addEventListener('input', () => renderFilterMenuOptions(state));
    menu.addEventListener('click', (event) => event.stopPropagation());
    renderFilterMenuOptions(state);
    const menuHeight = menu.offsetHeight;
    const below = rect.bottom + menuHeight + 8 <= window.innerHeight;
    menu.style.top = `${below ? rect.bottom + 6 : Math.max(8, rect.top - menuHeight - 6)}px`;
    search.focus({ preventScroll: true });
  }

  function makeHeader(label, key) {
    const th = document.createElement('th');
    th.className = 'result-filterable-heading';
    const content = document.createElement('div');
    content.className = 'result-th-content';
    const text = document.createElement('span');
    text.textContent = label;
    text.title = label;
    const button = document.createElement('button');
    button.className = 'result-filter-trigger';
    button.type = 'button';
    button.dataset.filterKey = key;
    button.dataset.filterLabel = label;
    button.setAttribute('aria-haspopup', 'dialog');
    button.setAttribute('aria-expanded', 'false');
    button.setAttribute('aria-label', `Filtrar ${label}`);
    button.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 3.25h11l-4.25 4.6v3.1l-2.5 1.3V7.85L2.5 3.25Z"/></svg>';
    button.addEventListener('click', (event) => {
      event.stopPropagation();
      openFilterMenu(key, label, button);
    });
    content.append(text, button);
    th.append(content);
    return th;
  }

  function renderHeader() {
    const head = $('#resultHead');
    const columns = result.columns || [];
    const showRowTotal = (result.metrics || []).length === 1 && (columns.length > 1 || columns[0] !== 'Total');
    const tr = document.createElement('tr');
    tr.append(makeHeader('Linha', 'row'));
    columns.forEach((label, index) => tr.append(makeHeader(label, `value:${index}`)));
    if (showRowTotal) tr.append(makeHeader('Total da linha', 'rowtotal'));
    head.replaceChildren(tr);
  }

  function renderColumnOptions(query = '') {
    const box = $('#columnOptions');
    const available = result?.availableColumns || [];
    const candidates = available.filter((item) => String(item.id) !== pendingMainColumn && !pendingAdditionalColumns.has(String(item.id)));
    const normalized = query.trim().toLocaleLowerCase('pt-BR');
    const matching = candidates.filter((item) => `${item.label} ${item.field}`.toLocaleLowerCase('pt-BR').includes(normalized));
    box.replaceChildren();
    if (!matching.length) {
      const empty = document.createElement('p');
      empty.className = 'result-column-empty';
      empty.textContent = candidates.length ? 'Nenhuma coluna corresponde à busca.' : 'Todas as opções compatíveis já estão no resultado.';
      box.append(empty);
      return;
    }
    matching.forEach((item) => {
      const label = document.createElement('label');
      label.className = 'result-column-option';
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.value = item.id;
      checkbox.disabled = isUpdatingColumns || pendingAdditionalColumns.size >= 2;
      const copy = document.createElement('span');
      const name = document.createElement('strong');
      name.textContent = item.label;
      const field = document.createElement('small');
      field.textContent = item.field;
      copy.append(name, field);
      label.append(checkbox, copy);
      checkbox.addEventListener('change', () => {
        if (checkbox.checked && pendingAdditionalColumns.size >= 2) {
          checkbox.checked = false;
          $('#columnHelp').textContent = 'O limite é de duas dimensões extras por resultado.';
          $('#columnHelp').classList.add('is-error');
          return;
        }
        pendingAdditionalColumns.add(String(item.id));
        renderActiveColumns();
        renderColumnOptions($('#columnSearch').value);
        updateColumnPickerState();
        $('#columnHelp').classList.remove('is-error');
        $('#applyColumns').disabled = isUpdatingColumns || sameColumnSelection();
      });
      box.append(label);
    });
  }

  function renderActiveColumns() {
    const box = $('#activeColumns');
    box.replaceChildren();
    const dimensions = new Map([...(result.columnDimensions || []), ...(result.availableColumns || [])].map((item) => [String(item.id), item]));
    const available = new Map((result.availableColumns || []).map((item) => [String(item.id), item]));
    const activeIds = [...new Set([pendingMainColumn, ...pendingAdditionalColumns].filter(Boolean))];
    for (const id of activeIds) {
      const item = dimensions.get(id) || available.get(id);
      if (!item) continue;
      const isMain = id === pendingMainColumn;
      const chip = document.createElement('span');
      chip.className = 'result-active-column';
      const name = document.createElement('strong');
      name.textContent = item.label;
      const detail = document.createElement('small');
      detail.textContent = isMain && id === String(result.column || '') ? 'já parametrizada' : 'adicionada';
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.setAttribute('aria-label', `Remover ${item.label}`);
      remove.textContent = 'Remover';
      remove.disabled = isUpdatingColumns;
      remove.addEventListener('click', () => {
        if (id === pendingMainColumn) pendingMainColumn = '';
        else pendingAdditionalColumns.delete(id);
        renderActiveColumns();
        renderColumnOptions($('#columnSearch').value);
        updateColumnPickerState();
        $('#columnHelp').classList.remove('is-error');
        submitColumnChanges();
      });
      chip.append(name, detail, remove);
      box.append(chip);
    }
  }

  function updateColumnPickerState() {
    const count = pendingAdditionalColumns.size;
    const measures = (result.metrics || []).length;
    $('#columnHelp').textContent = measures > 1
      ? `${count} de 2 dimensões extras. As categorias serão separadas por medida.`
      : `${count} de 2 dimensões extras. O cruzamento será recalculado.`;
    $('#applyColumns').disabled = isUpdatingColumns || sameColumnSelection();
  }

  function sameColumnSelection() {
    return pendingMainColumn === String(result.column || '')
      && sameColumns(pendingAdditionalColumns, result.additionalColumns || []);
  }

  function submitColumnChanges() {
    const picker = $('#columnPicker');
    if (!window.opener || isUpdatingColumns || pendingAdditionalColumns.size > 2) return;
    isUpdatingColumns = true;
    updateColumnPickerState();
    renderActiveColumns();
    renderColumnOptions($('#columnSearch').value);
    picker.open = false;
    $('#resultStatus').classList.remove('error');
    $('#resultStatus').textContent = 'Preparando o novo cruzamento com as colunas selecionadas…';
    window.opener.postMessage({
      type: 'tabwin2-add-result-columns',
      runId,
      column: pendingMainColumn || null,
      columns: [...pendingAdditionalColumns],
    }, location.origin);
  }

  function sameColumns(left, right) {
    const a = [...left].sort();
    const b = [...right].map(String).sort();
    return a.length === b.length && a.every((value, index) => value === b[index]);
  }

  function setupColumnPicker() {
    const picker = $('#columnPicker');
    const available = result.availableColumns || [];
    picker.hidden = !available.length;
    pendingMainColumn = String(result.column || '');
    pendingAdditionalColumns = new Set((result.additionalColumns || []).map(String));
    $('#columnSearch').value = '';
    $('#columnSearch').oninput = () => renderColumnOptions($('#columnSearch').value);
    $('#columnHelp').classList.remove('is-disabled', 'is-error');
    renderActiveColumns();
    updateColumnPickerState();
    $('#applyColumns').onclick = submitColumnChanges;
    renderColumnOptions();
  }

  function draw(data, updating = false) {
    const previous = result;
    if (updating && previous?.savedRecords && !data.savedRecords) data.savedRecords = previous.savedRecords;
    if (updating && previous) {
      const preserved = new Map();
      for (const key of ['row', 'rowtotal']) {
        const selected = filterState.get(key);
        if (selected === undefined || selected === null) continue;
        const available = new Set(distinctValuesFor(data, key));
        const kept = new Set([...selected].filter((value) => available.has(value)));
        if (kept.size < available.size) preserved.set(key, kept);
      }
      filterState = preserved;
    }
    result = data;
    closeFilterMenu();
    $('#resultTitle').textContent = 'Resultado da tabulação';
    const processed = Number(data.processedRecords || data.records || 0);
    const parts = [`${fmt(data.records)} registros incluídos`, `${fmt(processed)} registros lidos`, `${data.files?.length || 1} ${(data.files?.length || 1) === 1 ? 'arquivo' : 'arquivos'}`];
    if (data.appliedFilters) parts.push(`${fmt(data.appliedFilters)} categorias aplicadas`);
    if (data.municipalityApplied) parts.push(`atendimento em ${data.municipalityName || 'município selecionado'}`);
    if (data.municipalitySkipped) parts.push('filtro municipal indisponível nesta base; resultado considera todos os registros da base');
    if (data.excludedUnclassified) parts.push(`${fmt(data.excludedUnclassified)} não classificados ignorados`);
    $('#resultSummary').textContent = parts.join(' · ');

    const badges = $('#resultBadges');
    badges.replaceChildren();
    [...new Set([data.definition, ...(data.metrics || []).map((item) => item.label), ...(data.columnDimensions || []).map((item) => item.label)])].filter(Boolean).forEach((label) => {
      const item = document.createElement('span');
      item.className = 'result-badge';
      item.textContent = label;
      badges.append(item);
    });

    const saved = $('#savedDownload');
    saved.hidden = !data.savedRecords;
    if (data.savedRecords) {
      const link = document.createElement('a');
      link.href = data.savedRecords.url;
      link.className = 'button button-secondary';
      link.textContent = `Baixar ${data.savedRecords.name} · ${fmt(data.savedRecords.count)} registros`;
      saved.replaceChildren(link);
    }

    $('#resultTools').hidden = false;
    $('#resultPanel').hidden = false;
    renderHeader();
    setupColumnPicker();
    renderVisibleTable();
    $('#resultStatus').textContent = updating
      ? 'Colunas e totais atualizados. O filtro de linha foi mantido; filtros de valores foram reiniciados.'
      : data.truncated
        ? `Exibindo ${fmt(data.rows.length)} de ${fmt(data.totalCategories)} categorias. Os filtros locais consideram as linhas desta tela.`
        : 'Tabela mapeada e totalizada. Use os cabeçalhos para filtrar.';
    $('#resultStatus').classList.remove('error');
    $('#exportCsv').disabled = false;
    $('#printTable').disabled = false;
  }

  function escapeCsv(value) {
    return `"${String(value ?? '').replace(/"/g, '""')}"`;
  }

  $('#exportCsv').addEventListener('click', () => {
    if (!result) return;
    const rows = visibleRows();
    const columns = result.columns || [];
    const showRowTotal = (result.metrics || []).length === 1 && (columns.length > 1 || columns[0] !== 'Total');
    const header = ['Linha', ...columns];
    if (showRowTotal) header.push('Total da linha');
    const lines = [header, ...rows.map((row) => {
      const values = [row.label, ...(row.values || [])];
      if (showRowTotal) values.push((row.values || []).reduce((sum, value) => sum + numeric(value), 0));
      return values;
    })];
    const filtered = activeFilterCount() > 0;
    const totals = columns.map((_, index) => filtered
      ? rows.reduce((sum, row) => sum + numeric(row.values?.[index]), 0)
      : numeric(result.columnTotals?.[index]));
    lines.push(['Total geral', ...totals, ...(showRowTotal ? [filtered ? totals.reduce((sum, value) => sum + value, 0) : result.total] : [])]);
    const blob = new Blob(['\ufeff' + lines.map((row) => row.map(escapeCsv).join(';')).join('\r\n')], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'tabulacao-spptab.csv';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });

  $('#printTable').addEventListener('click', () => window.print());
  $('#columnPicker').addEventListener('toggle', () => {
    if ($('#columnPicker').open) $('#columnSearch').focus({ preventScroll: true });
  });
  document.addEventListener('click', () => closeFilterMenu());
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeFilterMenu();
  });
  window.addEventListener('scroll', () => closeFilterMenu(), true);
  window.addEventListener('resize', () => closeFilterMenu());

  if (!/^[a-f0-9]{32}$/.test(runId || '')) {
    showError('Identificador de execução inválido.');
    return;
  }
  window.addEventListener('message', (event) => {
    if (event.origin !== location.origin || event.source !== window.opener) return;
    const message = event.data || {};
    if (message.runId !== runId) return;
    if (message.type === 'tabwin2-result' && message.data?.ok) draw(message.data);
    else if (message.type === 'tabwin2-result-update' && message.data?.ok) {
      isUpdatingColumns = false;
      draw(message.data, true);
    }
    else if (message.type === 'tabwin2-column-error') {
      isUpdatingColumns = false;
      $('#resultStatus').textContent = message.message || 'Não foi possível atualizar as colunas.';
      $('#resultStatus').classList.add('error');
      renderActiveColumns();
      renderColumnOptions($('#columnSearch').value);
      $('#applyColumns').disabled = isUpdatingColumns || sameColumnSelection();
    } else if (message.type === 'tabwin2-error') showError(message.message || 'Falha ao gerar a tabulação.');
    else if (message.type === 'tabwin2-progress') {
      const progress = Number(message.progress) || 0;
      $('#resultStatus').textContent = result
        ? `Atualizando o cruzamento · ${progress}% · ${message.stage || 'Lendo os dados'}`
        : `${progress}% concluído · ${message.stage || 'Lendo os dados'}`;
      if (!result) {
        $('#resultTitle').textContent = 'Tabulação em andamento';
        $('#resultSummary').textContent = message.stage || 'Lendo os dados…';
      }
    }
  });
  if (window.opener) window.opener.postMessage({ type: 'tabwin2-result-ready', runId }, location.origin);
  else showError('A janela de tabulação foi fechada antes do envio do resultado.');
})();
