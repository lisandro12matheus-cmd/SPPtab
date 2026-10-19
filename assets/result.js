(() => {
  'use strict';
  const $ = (selector) => document.querySelector(selector);
  const params = new URLSearchParams(location.search);
  const runId = params.get('run');
  const MAX_FILTER_OPTIONS = 250;
  let result = null;
  let activeFilterMenu = null;
  let filterState = new Map();
  const filterSortDirections = new Map();
  let resultFilterRows = [];
  let isUpdatingResultFilters = false;
  let resultFilterError = '';
  let filterRowSequence = 0;
  let filterRequestSequence = 0;
  const pendingFilterValueRequests = new Map();


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

  function numberForSort(value) {
    const raw = String(value ?? '').trim().replace(/\s/g, '');
    if (!raw) return null;
    const normalized = raw.includes(',')
      ? raw.includes('.') ? raw.replace(/\./g, '').replace(',', '.') : raw.replace(',', '.')
      : raw;
    if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(normalized)) return null;
    const number = Number(normalized);
    return Number.isFinite(number) ? number : null;
  }

  function sortFilterValues(values, direction) {
    const nonempty = values.filter((value) => String(value).trim() !== '');
    const numericValues = nonempty.map(numberForSort);
    const numericSort = nonempty.length > 0 && numericValues.every((value) => value !== null);
    const sign = direction === 'desc' ? -1 : 1;
    const sorted = [...values].sort((left, right) => {
      const leftEmpty = String(left).trim() === '';
      const rightEmpty = String(right).trim() === '';
      if (leftEmpty !== rightEmpty) return leftEmpty ? 1 : -1;
      const comparison = numericSort
        ? numberForSort(left) - numberForSort(right)
        : left.localeCompare(right, 'pt-BR', { numeric: true, sensitivity: 'base' });
      return comparison * sign;
    });
    return { values: sorted, numericSort };
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
    const direction = filterSortDirections.get(state.key) || 'asc';
    const sorted = sortFilterValues(all, direction);
    const selected = filterState.get(state.key);
    const query = state.search.value.trim().toLocaleLowerCase('pt-BR');
    const matches = query ? sorted.values.filter((value) => value.toLocaleLowerCase('pt-BR').includes(query)) : sorted.values;
    const shown = matches.slice(0, MAX_FILTER_OPTIONS);
    state.sortButton.textContent = sorted.numericSort
      ? direction === 'asc' ? 'Menor → maior' : 'Maior → menor'
      : direction === 'asc' ? 'A → Z' : 'Z → A';
    state.sortButton.setAttribute('aria-label', `Ordenar ${state.key === 'row' ? 'linhas' : 'valores'} ${direction === 'asc' ? 'em ordem decrescente' : 'em ordem crescente'}`);
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
    const sortButton = document.createElement('button');
    sortButton.type = 'button';
    sortButton.className = 'result-filter-sort';
    actions.append(allButton, noneButton, sortButton);
    const count = document.createElement('div');
    count.className = 'result-filter-count';
    const list = document.createElement('div');
    list.className = 'result-filter-list';
    const limit = document.createElement('p');
    limit.className = 'result-filter-limit';
    menu.append(heading, search, actions, count, list, limit);
    document.body.append(menu);

    const state = { key, trigger, menu, search, count, list, limit, sortButton };
    activeFilterMenu = state;
    trigger.setAttribute('aria-expanded', 'true');
    const rect = trigger.getBoundingClientRect();
    const menuWidth = Math.min(310, window.innerWidth - 20);
    menu.style.width = `${menuWidth}px`;
    menu.style.left = `${Math.max(10, Math.min(rect.right - menuWidth, window.innerWidth - menuWidth - 10))}px`;

    allButton.addEventListener('click', () => setFilter(key, null));
    noneButton.addEventListener('click', () => setFilter(key, new Set()));
    sortButton.addEventListener('click', () => {
      filterSortDirections.set(key, (filterSortDirections.get(key) || 'asc') === 'asc' ? 'desc' : 'asc');
      renderFilterMenuOptions(state);
    });
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

  function resultFilterKey(optionType, option) {
    return `${optionType}:${option}`;
  }

  function availableResultFilterOptions() {
    const options = new Map();
    for (const item of result?.filterOptions || []) options.set(resultFilterKey(item.optionType, item.id), item);
    for (const row of resultFilterRows) {
      if (row.option && row.optionType) {
        const key = resultFilterKey(row.optionType, row.option);
        if (!options.has(key)) {
          // `row.id` identifica a linha visual; aqui `id` precisa ser o ID
          // oficial da variável para que o select continue selecionado.
          options.set(key, { id: row.option, option: row.option, optionType: row.optionType, label: row.label, field: row.field });
        }
      }
    }
    return [...options.values()];
  }

  function preserveAppliedResultFilters(filters) {
    const previousRows = resultFilterRows;
    const rowsByKey = new Map(previousRows
      .filter((row) => row.option && row.optionType)
      .map((row) => [resultFilterKey(row.optionType, row.option), row]));
    const appliedRows = (filters || []).map((filter) => {
      const option = String(filter.option || '');
      const optionType = String(filter.optionType || '');
      const key = resultFilterKey(optionType, option);
      const row = rowsByKey.get(key) || {
        id: `result-filter-${++filterRowSequence}`,
        option,
        optionType,
        label: String(filter.label || ''),
        field: '',
        value: '',
        values: [],
        truncated: false,
        loading: false,
        error: '',
        requestId: '',
      };
      row.option = option;
      row.optionType = optionType;
      row.value = String(filter.value || '');
      if (filter.label) row.label = String(filter.label);
      return row;
    });
    const appliedIds = new Set(appliedRows.map((row) => row.id));
    const drafts = previousRows.filter((row) => (!row.option || !row.value) && !appliedIds.has(row.id));
    resultFilterRows = [...appliedRows, ...drafts];
    appliedRows.filter((row) => !row.values.length && !row.loading).forEach(requestResultFilterValues);
  }

  function resultFilterPayload() {
    return resultFilterRows
      .filter((row) => row.option && row.optionType && row.value)
      .map((row) => ({ option: row.option, optionType: row.optionType, value: row.value, label: row.label, mode: 'include' }));
  }

  function sameResultFilters(left, right) {
    const normalize = (items) => (items || []).map((item) => `${item.optionType}:${item.option}=${item.value}`).sort();
    const a = normalize(left);
    const b = normalize(right);
    return a.length === b.length && a.every((value, index) => value === b[index]);
  }

  function requestResultFilterValues(row) {
    if (!window.opener || !row.option || !row.optionType || isUpdatingResultFilters) return;
    resultFilterError = '';
    $('#resultStatus').classList.remove('error');
    row.loading = true;
    row.error = '';
    row.values = [];
    const requestId = `${runId}-${++filterRequestSequence}`;
    row.requestId = requestId;
    pendingFilterValueRequests.set(requestId, row.id);
    renderResultFilters();
    window.opener.postMessage({
      type: 'tabwin2-load-result-filter-values',
      runId,
      requestId,
      option: row.option,
      optionType: row.optionType,
    }, location.origin);
  }

  function handleResultFilterValues(message) {
    const rowId = pendingFilterValueRequests.get(message.requestId);
    pendingFilterValueRequests.delete(message.requestId);
    const row = resultFilterRows.find((item) => item.id === rowId);
    if (!row || row.option !== message.option || row.optionType !== message.optionType) return;
    row.loading = false;
    row.error = message.error || '';
    row.values = message.data?.values || [];
    row.truncated = Boolean(message.data?.truncated);
    if (!row.error) resultFilterError = '';
    if (row.value && !row.values.some((item) => String(item.value) === row.value)) row.value = '';
    renderResultFilters();
  }

  function addResultFilterRow(initial = null) {
    const row = {
      id: `result-filter-${++filterRowSequence}`,
      option: String(initial?.option || ''),
      optionType: String(initial?.optionType || ''),
      label: String(initial?.label || ''),
      field: String(initial?.field || ''),
      value: String(initial?.value || ''),
      values: [],
      truncated: false,
      loading: false,
      error: '',
      requestId: '',
    };
    resultFilterRows.push(row);
    if (row.option && row.optionType) requestResultFilterValues(row);
    renderResultFilters();
    return row;
  }

  function renderResultFilters() {
    const box = $('#resultFilterRows');
    const builder = $('#resultFilterBuilder');
    const addButton = $('#addResultFilter');
    const anotherButton = $('#addAnotherResultFilter');
    const allOptions = availableResultFilterOptions();
    const available = result?.filterOptions || [];
    builder.hidden = resultFilterRows.length === 0;
    addButton.hidden = !available.length && resultFilterRows.length === 0;
    anotherButton.hidden = !available.length;
    anotherButton.disabled = isUpdatingResultFilters;
    box.replaceChildren();

    resultFilterRows.forEach((row) => {
      const container = document.createElement('div');
      container.className = 'result-filter-row';
      const fieldLabel = document.createElement('label');
      fieldLabel.textContent = 'Informação';
      const fieldSelect = document.createElement('select');
      fieldSelect.setAttribute('aria-label', 'Informação para filtrar');
      fieldSelect.add(new Option('Escolha uma informação', ''));
      const usedByOthers = new Set(resultFilterRows.filter((item) => item.id !== row.id && item.option && item.optionType).map((item) => resultFilterKey(item.optionType, item.option)));
      allOptions.forEach((item) => {
        const key = resultFilterKey(item.optionType, item.id || item.option);
        if (usedByOthers.has(key)) return;
        const value = resultFilterKey(item.optionType, item.id || item.option);
        fieldSelect.add(new Option(item.label, value));
      });
      fieldSelect.value = row.option ? resultFilterKey(row.optionType, row.option) : '';
      fieldSelect.disabled = isUpdatingResultFilters;
      fieldSelect.addEventListener('change', () => {
        resultFilterError = '';
        $('#resultStatus').classList.remove('error');
        const oldValue = row.value;
        const selected = allOptions.find((item) => resultFilterKey(item.optionType, item.id || item.option) === fieldSelect.value);
        row.option = String(selected?.id || selected?.option || '');
        row.optionType = String(selected?.optionType || '');
        row.label = String(selected?.label || '');
        row.field = String(selected?.field || '');
        row.value = '';
        row.values = [];
        row.truncated = false;
        row.error = '';
        renderResultFilters();
        if (row.option) requestResultFilterValues(row);
        if (oldValue) submitResultFilters();
      });
      fieldLabel.append(fieldSelect);

      const valueLabel = document.createElement('label');
      valueLabel.textContent = 'Categoria';
      const valueSelect = document.createElement('select');
      valueSelect.setAttribute('aria-label', `Categoria para ${row.label || 'o filtro'}`);
      if (!row.option) valueSelect.add(new Option('Escolha primeiro a informação', ''));
      else if (row.loading) valueSelect.add(new Option('Carregando categorias…', ''));
      else if (row.error) valueSelect.add(new Option('Falha ao carregar categorias', ''));
      else {
        valueSelect.add(new Option(row.values.length ? 'Escolha uma categoria' : 'Nenhuma categoria disponível', ''));
        row.values.forEach((item) => {
          const code = String(item.value);
          const label = item.label && item.label !== code ? `${item.label} · código ${code}` : code;
          valueSelect.add(new Option(label, code));
        });
      }
      valueSelect.value = row.value;
      valueSelect.disabled = isUpdatingResultFilters || !row.option || row.loading || Boolean(row.error) || !row.values.length;
      valueSelect.addEventListener('change', () => {
        row.value = valueSelect.value;
        submitResultFilters();
      });
      valueLabel.append(valueSelect);

      const remove = document.createElement('button');
      remove.type = 'button';
      remove.textContent = 'Remover';
      remove.disabled = isUpdatingResultFilters;
      remove.setAttribute('aria-label', `Remover filtro ${row.label || ''}`.trim());
      remove.addEventListener('click', () => {
        resultFilterError = '';
        $('#resultStatus').classList.remove('error');
        const hadValue = Boolean(row.option && row.value);
        resultFilterRows = resultFilterRows.filter((item) => item.id !== row.id);
        renderResultFilters();
        if (hadValue) submitResultFilters();
      });
      const status = document.createElement('p');
      status.className = `result-filter-row__status${row.error ? ' error' : ''}`;
      const truncatedNotice = 'A lista tem mais de 5.000 categorias; refine a consulta principal para reduzir as opções.';
      status.textContent = row.error || (isUpdatingResultFilters ? 'Aplicando o filtro ao resultado…' : resultFilterError ? 'Não foi possível aplicar; ajuste o filtro e tente novamente.' : row.loading ? 'Carregando as categorias deste campo…' : !row.option ? 'Escolha a informação que deseja filtrar.' : !row.values.length ? 'Este campo não tem categorias disponíveis nesta base.' : row.value ? `Filtro aplicado ao resultado.${row.truncated ? ` ${truncatedNotice}` : ''}` : row.truncated ? truncatedNotice : 'Selecione uma categoria para aplicar o filtro.');
      container.append(fieldLabel, valueLabel, remove, status);
      box.append(container);
    });

    if (isUpdatingResultFilters) $('#resultFilterHelp').textContent = 'Recalculando a base com os filtros escolhidos…';
    else if (!available.length && resultFilterRows.length) $('#resultFilterHelp').textContent = 'Todas as informações compatíveis já estão sendo usadas como filtro.';
    else $('#resultFilterHelp').textContent = 'Os filtros selecionados serão aplicados à base e aos totais.';
    if (resultFilterError) $('#resultFilterHelp').textContent = resultFilterError;
    $('#resultFilterHelp').classList.toggle('error', Boolean(resultFilterError));
    addButton.disabled = isUpdatingResultFilters || !available.length;
  }

  function submitResultFilters() {
    if (!window.opener || isUpdatingResultFilters) return;
    const filters = resultFilterPayload();
    if (sameResultFilters(filters, result?.resultFilters || [])) return;
    isUpdatingResultFilters = true;
    resultFilterError = '';
    $('#resultStatus').classList.remove('error');
    $('#resultStatus').textContent = 'Preparando o novo cruzamento com os filtros escolhidos…';
    renderResultFilters();
    window.opener.postMessage({ type: 'tabwin2-result-filters', runId, filters }, location.origin);
  }

  function setupResultFilters(updating = false) {
    if (!updating) {
      resultFilterRows = [];
      (result.resultFilters || []).forEach((filter) => addResultFilterRow(filter));
    }
    $('#addResultFilter').onclick = () => {
      resultFilterError = '';
      $('#resultStatus').classList.remove('error');
      $('#resultFilterBuilder').hidden = false;
      addResultFilterRow();
    };
    $('#addAnotherResultFilter').onclick = () => {
      resultFilterError = '';
      $('#resultStatus').classList.remove('error');
      addResultFilterRow();
    };
    renderResultFilters();
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
    if (updating && Array.isArray(data.resultFilters)) preserveAppliedResultFilters(data.resultFilters);
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
    setupResultFilters(updating);
    renderVisibleTable();
    $('#resultStatus').textContent = updating
      ? 'Resultado recalculado. Os filtros locais dos cabeçalhos foram reiniciados para refletir os novos dados.'
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

    const blob = new Blob(['\ufeff' + lines.map((row) => row.map(escapeCsv).join(';')).join('\r\n')], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'tabulacao-spptab.csv';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });

  $('#printTable').addEventListener('click', () => window.print());

  document.addEventListener('click', (event) => {
    if (!activeFilterMenu) return;
    const target = event.target;
    if (target instanceof Node && (activeFilterMenu.menu.contains(target) || activeFilterMenu.trigger.contains(target))) return;
    closeFilterMenu();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeFilterMenu();
  });
  window.addEventListener('scroll', (event) => {
    // A rolagem da lista de opções faz parte da navegação do filtro; só feche
    // quando a página ou outro elemento fora do menu for rolado.
    if (event.target instanceof Node && activeFilterMenu?.menu.contains(event.target)) return;
    closeFilterMenu();
  }, true);
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
    else if (message.type === 'tabwin2-filter-values') handleResultFilterValues(message);
    else if (message.type === 'tabwin2-result-update' && message.data?.ok) {
      isUpdatingResultFilters = false;
      draw(message.data, true);
    }
    else if (message.type === 'tabwin2-filter-error') {
      isUpdatingResultFilters = false;
      resultFilterError = message.message || 'Não foi possível aplicar os filtros.';
      $('#resultStatus').textContent = message.message || 'Não foi possível aplicar os filtros.';
      $('#resultStatus').classList.add('error');
      renderResultFilters();
    } else if (message.type === 'tabwin2-error') showError(message.message || 'Falha ao gerar a tabulação.');
    else if (message.type === 'tabwin2-progress') {
      const progress = Number(message.progress) || 0;
      $('#resultStatus').textContent = result
        ? `Atualizando o cruzamento · ${progress}% · ${message.stage || 'Lendo os dados'}`
        : `${progress}% concluído · ${message.stage || 'Lendo os dados'}`;
      if (isUpdatingResultFilters) $('#resultFilterHelp').textContent = `Recalculando a base · ${progress}% · ${message.stage || 'Aplicando filtros'}`;
      if (!result) {
        $('#resultTitle').textContent = 'Tabulação em andamento';
        $('#resultSummary').textContent = message.stage || 'Lendo os dados…';
      }
    }
  });
  if (window.opener) window.opener.postMessage({ type: 'tabwin2-result-ready', runId }, location.origin);
  else showError('A janela de tabulação foi fechada antes do envio do resultado.');
})();
