(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const number = new Intl.NumberFormat('pt-BR');
  const money = (cents) => cents === null || cents === undefined ? 'Não informado' : new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(cents / 100);
  const age = (raw) => raw === null || raw === undefined || raw === '' ? 'Não informado' : raw === '9999' ? 'Sem restrição cadastrada' : `${Number(raw)} meses (${Math.floor(Number(raw) / 12)} ano(s) e ${Number(raw) % 12} mês(es))`;
  const competenceLabel = (value) => value ? `${value.slice(4, 6)}/${value.slice(0, 4)}` : 'Não informada';
  const names = { group: 'Grupo', subgroup: 'Subgrupo', form: 'Forma de organização', complexity: 'Complexidade', financing: 'Financiamento', modality: 'Modalidade', registration: 'Instrumento de registro', cbo: 'CBO', cid: 'CID', service_class: 'Serviço / classificação', habilitation: 'Habilitação', detail: 'Detalhe', bed: 'Tipo de leito', rule: 'Regra', compatible: 'Procedimento compatível', increment: 'Incremento', sex: 'Sexo', ageYears: 'Idade', minValue: 'Valor mínimo', maxValue: 'Valor máximo', query: 'Pesquisa' };
  const state = { view: 'explore', page: 1, comparePage: 1, count: 0, compareCount: 0, sequence: 0 };
  const columnNames = { code:'Código', name:'Procedimento', group:'Grupo', complexity:'Complexidade', financing:'Financiamento', sa:'Valor SA', sh:'Valor SH', sp:'Valor SP' };
  const columnSort = { code:'code', name:'name', group:'group', complexity:'complexity', financing:'financing', sa:'value_sa', sh:'value_sh', sp:'value_sp' };
  const columnFilters = {};
  let columnMenu = null;
  const el = (tag, className, value) => { const node = document.createElement(tag); if (className) node.className = className; if (value !== undefined) node.textContent = String(value); return node; };
  const append = (parent, ...children) => { children.forEach(child => parent.append(child)); return parent; };
  const option = (value, label) => new Option(label, value);
  const headingActions = el('div', 'sg-heading-actions');
  const sourceLink = document.querySelector('.sg-source-link');
  sourceLink.replaceWith(headingActions);
  const zipButton = el('button', 'button button-secondary sg-action-button', 'Baixar ZIP oficial');
  zipButton.type = 'button'; zipButton.disabled = true;
  const zipStatus = el('span', 'sg-download-status');
  zipStatus.setAttribute('role', 'status');
  zipStatus.hidden = true;
  headingActions.append(sourceLink, zipButton, zipStatus);
  const procedureCsvButton = el('button', 'button button-secondary sg-action-button', 'Baixar CSV');
  procedureCsvButton.type = 'button'; procedureCsvButton.disabled = true;
  document.querySelector('.sg-table-head').append(procedureCsvButton);
  const compareCsvButton = el('button', 'button button-secondary sg-action-button', 'Baixar CSV');
  compareCsvButton.type = 'button'; compareCsvButton.disabled = true;
  document.querySelector('#compareView .sg-section-head').append(compareCsvButton);

  function saveCsv(filename, headers, rows) {
    const cell = (value, preserveCode = false) => {
      let textValue = value === null || value === undefined ? '' : String(value);
      if (/^\s*[=+\-@]/.test(textValue) || (preserveCode && /^\d+$/.test(textValue))) textValue = "'" + textValue;
      return `"${textValue.replace(/"/g, '""')}"`;
    };
    const csv = '\uFEFF' + [headers, ...rows].map((row, index) => row.map((value, column) => cell(value, index > 0 && column === 0)).join(';')).join('\r\n');
    const url = URL.createObjectURL(new Blob([csv], {type:'text/csv;charset=utf-8'}));
    const link = el('a'); link.href = url; link.download = filename;
    document.body.append(link); link.click(); link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const csvMoney = (cents) => cents === null || cents === undefined ? '' : (Number(cents) / 100).toFixed(2).replace('.', ',');

  async function api(payload) {
    const response = await fetch('api.php', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-SPPtab-CSRF': csrf }, body: JSON.stringify(payload), cache: 'no-store' });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.ok === false) throw new Error(result.error || result.message || `Falha na consulta (${response.status}).`);
    return result;
  }
  function message(target, textValue, error = false) { const node = $(target); node.hidden = !textValue; node.textContent = textValue || ''; node.classList.toggle('is-error', error); }
  function source(sourceData, fallback) {
    if (!sourceData) return;
    const parts = [`SIGTAP · competência ${competenceLabel(sourceData.competence)}`, `consultada em ${new Date(sourceData.loadedAt).toLocaleString('pt-BR')}`, sourceData.filename];
    if (sourceData.warning) parts.push(sourceData.warning);
    else if (fallback) parts.push(fallback);
    $('sourceStatus').textContent = parts.filter(Boolean).join(' · ');
    $('sourceStatus').classList.toggle('is-warning', Boolean(sourceData.warning));
  }
  function filters() {
    const result = {};
    document.querySelectorAll('[data-filter]').forEach(node => { if (node.value !== '') result[node.dataset.filter] = node.value; });
    const query = $('query').value.trim(); if (query) result.query = query;
    const age = $('filterAge').value; if (age !== '') result.ageYears = Number(age);
    const min = $('minValue').value; if (min !== '') result.minValue = Math.round(Number(min) * 100);
    const max = $('maxValue').value; if (max !== '') result.maxValue = Math.round(Number(max) * 100);
    if (min !== '' || max !== '') result.valueComponent = $('valueComponent').value;
    return result;
  }
  function activeFilters() {
    const values = filters(); const panel = $('activeFilters'); panel.replaceChildren();
    const shown = Object.entries(values).filter(([key]) => key !== 'valueComponent');
    const activeTotal = shown.length + Object.keys(columnFilters).length;
    $('activeCount').textContent = `${activeTotal} ativo${activeTotal === 1 ? '' : 's'}`;
    shown.forEach(([key, value]) => {
      let label = value;
      const select = document.querySelector(`[data-filter="${key}"]`);
      if (select) label = select.selectedOptions[0]?.textContent || value;
      if (key === 'minValue' || key === 'maxValue') label = money(value);
      if (key === 'ageYears') label += ' anos';
      const chip = el('button', 'sg-chip', `${names[key] || key}: ${label} ×`);
      chip.type = 'button'; chip.addEventListener('click', () => {
        if (select) select.value = ''; else if (key === 'query') $('query').value = ''; else if (key === 'ageYears') $('filterAge').value = ''; else $(key).value = '';
        state.page = 1; refresh();
      }); panel.append(chip);
    });
    Object.entries(columnFilters).forEach(([key, spec]) => {
      const count = spec.values.length;
      const chip = el('button', 'sg-chip', `${columnNames[key]}: ${spec.mode === 'include' ? count + ' selecionado(s)' : count + ' excluído(s)'} ×`);
      chip.type = 'button'; chip.addEventListener('click', () => { delete columnFilters[key]; state.page = 1; refresh(); });
      panel.append(chip);
    });
  }
  function setView(view) {
    closeColumnMenu();
    state.view = view;
    for (const name of ['explore', 'reports', 'compare']) $(name + 'View').hidden = name !== view;
    document.querySelectorAll('[data-view]').forEach(tab => { const active = tab.dataset.view === view; tab.classList.toggle('active', active); tab.setAttribute('aria-selected', String(active)); });
    if (view === 'reports') { loadReports(); loadRelationOptions(); }
    if (view === 'compare' && !$('compareRows').children.length) loadCompare();
  }
  function fillSelect(select, rows, firstLabel) {
    const previous = select.value;
    select.replaceChildren(option('', firstLabel));
    rows.forEach(row => select.add(option(row.code, `${row.code} · ${row.label}`)));
    if ([...select.options].some(item => item.value === previous)) select.value = previous;
  }
  async function loadOptions(kind, query = '') {
    const data = await api({ action: 'sigtap_options', competence: $('competence').value, kind, query });
    const select = document.querySelector(`[data-filter="${kind}"]`);
    const defaults = { group: 'Todos', subgroup: 'Todos', form: 'Todas', financing: 'Todos', modality: 'Todas', registration: 'Todos', cbo: 'Qualquer CBO', cid: 'Qualquer CID', service_class: 'Qualquer serviço / classificação', habilitation: 'Qualquer habilitação' };
    fillSelect(select, data.options, defaults[kind] || 'Todos');
    if (data.truncated) select.title = 'Mostrando 200 opções. Digite para pesquisar outras.';
  }
  function procedureRow(item) {
    const tr = el('tr');
    const code = el('button', 'sg-link', item.code); code.type = 'button'; code.addEventListener('click', () => openDetail(item.code));
    const cells = [item.name, item.group?.label || 'Não informado', item.complexity?.label || 'Não informado', item.financing ? `${item.financing.code} · ${item.financing.label}` : 'Não informado', money(item.values?.sa), money(item.values?.sh), money(item.values?.sp)];
    tr.append(append(el('td', 'sg-procedure'), el('strong', '', cells[0])));
    cells.slice(1).forEach((value, index) => tr.append(el('td', index >= 3 ? 'sg-number' : '', value)));
    tr.prepend(append(el('td'), code));
    return tr;
  }
  async function loadSearch() {
    const sequence = ++state.sequence;
    const selected = $('competence').value; if (!selected) return;
    activeFilters(); $('loader').hidden = false; message('message', '');
    try {
      const data = await api({ action: 'sigtap_search', competence: selected, filters: filters(), columnFilters, page: state.page, pageSize: Number($('pageSize').value), sort: $('sort').value, direction: $('direction').value });
      if (sequence !== state.sequence) return;
      source(data.source); state.count = data.count;
      $('resultCount').textContent = `${number.format(data.count)} procedimento${data.count === 1 ? '' : 's'}`;
      $('resultContext').textContent = `Competência ${competenceLabel(selected)} · dados de referência SIGTAP`;
      $('procedureRows').replaceChildren(...data.rows.map(procedureRow));
      $('tableWrap').hidden = data.rows.length === 0;
      procedureCsvButton.disabled = data.count === 0;
      if (!data.rows.length) message('message', 'Nenhum procedimento corresponde a esses filtros.');
      $('pageInfo').textContent = `Página ${data.page} de ${Math.max(1, Math.ceil(data.count / data.pageSize))}`;
      $('previousPage').disabled = data.page <= 1;
      $('nextPage').disabled = data.page * data.pageSize >= data.count;
    } catch (error) { if (sequence === state.sequence) { $('tableWrap').hidden = true; procedureCsvButton.disabled = true; message('message', error.message, true); } }
    finally { if (sequence === state.sequence) $('loader').hidden = true; }
  }
  function closeColumnMenu() {
    if (columnMenu) { columnMenu.remove(); columnMenu = null; }
    document.querySelectorAll('.sg-column-trigger').forEach(button => button.setAttribute('aria-expanded', 'false'));
  }
  function columnValueLabel(column, item) {
    if (item.value === '') return 'Não informado';
    if (['sa','sh','sp'].includes(column)) return money(Number(item.value));
    if (['group','complexity','financing'].includes(column)) return `${item.value} · ${item.label}`;
    return item.label;
  }
  async function openColumnMenu(button) {
    if (!$('competence').value) return;
    const column = button.dataset.column;
    if (columnMenu?.dataset.column === column) { closeColumnMenu(); return; }
    closeColumnMenu();
    const menu = el('div', 'sg-column-menu'); menu.dataset.column = column; menu.setAttribute('role', 'dialog');
    menu.setAttribute('aria-label', `Filtrar ${columnNames[column]}`);
    menu.append(el('strong', 'sg-column-title', columnNames[column]), el('p', 'sg-column-status', 'Carregando valores da competência…'));
    document.body.append(menu); columnMenu = menu; button.setAttribute('aria-expanded', 'true');
    const rect = button.getBoundingClientRect(), width = 330;
    menu.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - width - 8))}px`;
    const below = window.innerHeight - rect.bottom - 12, above = rect.top - 12;
    const placeBelow = below >= 240 || below >= above;
    const availableHeight = Math.min(550, Math.max(190, placeBelow ? below : above));
    menu.style.maxHeight = `${availableHeight}px`;
    menu.style.top = `${placeBelow ? rect.bottom + 5 : Math.max(8, rect.top - availableHeight - 5)}px`;
    try {
      const data = await api({ action:'sigtap_column_values', competence:$('competence').value, column, filters:filters(), columnFilters });
      if (columnMenu !== menu) return;
      const items = data.values || [];
      const universe = items.map(item => item.value);
      const current = columnFilters[column];
      const selected = new Set(universe.filter(value => !current || (current.mode === 'include' ? current.values.includes(value) : !current.values.includes(value))));
      const search = el('input', 'sg-column-search'); search.type = 'search'; search.placeholder = 'Pesquisar valores…'; search.setAttribute('aria-label', `Pesquisar valores em ${columnNames[column]}`);
      const actions = el('div', 'sg-column-actions');
      const selectAll = el('button', '', 'Selecionar todos'); selectAll.type = 'button';
      const deselectAll = el('button', '', 'Desmarcar todos'); deselectAll.type = 'button';
      const clear = el('button', '', 'Limpar filtro'); clear.type = 'button';
      actions.append(selectAll, deselectAll, clear);
      const count = el('small', 'sg-column-count');
      const list = el('div', 'sg-column-options');
      list.style.maxHeight = `${Math.max(90, availableHeight - 215)}px`;
      const footer = el('div', 'sg-column-footer');
      const cancel = el('button', '', 'Cancelar'); cancel.type = 'button'; cancel.addEventListener('click', closeColumnMenu);
      const apply = el('button', 'sg-column-apply', 'Aplicar filtro'); apply.type = 'button';
      footer.append(cancel, apply);
      menu.replaceChildren(el('strong', 'sg-column-title', columnNames[column]), search, actions, count, list, footer);
      const normalized = value => String(value).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR');
      const visibleItems = () => items.filter(item => normalized(columnValueLabel(column,item)).includes(normalized(search.value.trim())));
      function render() {
        const shown = visibleItems(); list.replaceChildren();
        for (const item of shown.slice(0, 200)) {
          const label = el('label', 'sg-column-option');
          const check = document.createElement('input'); check.type = 'checkbox'; check.checked = selected.has(item.value);
          check.addEventListener('change', () => { if (check.checked) selected.add(item.value); else selected.delete(item.value); count.textContent = `${selected.size} de ${items.length} selecionados${shown.length > 200 ? ' · exibindo 200; pesquise para ver outros' : ''}`; });
          label.append(check, el('span', '', columnValueLabel(column,item))); list.append(label);
        }
        if (!shown.length) list.append(el('p', 'sg-column-empty', 'Nenhum valor encontrado.'));
        count.textContent = `${selected.size} de ${items.length} selecionados${shown.length > 200 ? ' · exibindo 200; pesquise para ver outros' : ''}`;
      }
      search.addEventListener('input', render);
      selectAll.addEventListener('click', () => { visibleItems().forEach(item => selected.add(item.value)); render(); });
      deselectAll.addEventListener('click', () => { visibleItems().forEach(item => selected.delete(item.value)); render(); });
      clear.addEventListener('click', () => { delete columnFilters[column]; closeColumnMenu(); state.page = 1; refresh(); });
      apply.addEventListener('click', () => {
        if (selected.size === universe.length) delete columnFilters[column];
        else {
          const excluded = universe.filter(value => !selected.has(value));
          columnFilters[column] = selected.size <= excluded.length ? { mode:'include', values:[...selected] } : { mode:'exclude', values:excluded };
        }
        closeColumnMenu(); state.page = 1; refresh();
      });
      const sort = el('div', 'sg-column-sort');
      for (const [direction, label] of [['asc', ['sa','sh','sp'].includes(column) ? 'Menor → maior' : 'A → Z'], ['desc', ['sa','sh','sp'].includes(column) ? 'Maior → menor' : 'Z → A']]) {
        const control = el('button', '', label); control.type = 'button';
        control.addEventListener('click', () => { $('sort').value = columnSort[column]; $('direction').value = direction; closeColumnMenu(); state.page = 1; loadSearch(); });
        sort.append(control);
      }
      menu.insertBefore(sort, footer); render();
    } catch (error) { if (columnMenu === menu) menu.replaceChildren(el('p', 'sg-error', error.message)); }
  }
  const fieldNames = { CO_PROCEDIMENTO: 'Código', NO_PROCEDIMENTO: 'Nome', TP_COMPLEXIDADE: 'Complexidade', TP_SEXO: 'Sexo', CO_FINANCIAMENTO: 'Financiamento', VL_SH: 'Valor hospitalar SH', VL_SA: 'Valor ambulatorial SA', VL_SP: 'Valor profissional SP', VL_IDADE_MINIMA: 'Idade mínima', VL_IDADE_MAXIMA: 'Idade máxima', QT_MAXIMA_EXECUCAO: 'Execuções máximas', QT_DIAS_PERMANENCIA: 'Dias de permanência', QT_TEMPO_PERMANENCIA: 'Tempo de permanência', QT_PONTOS: 'Pontos' };
  function block(title, content) { const section = el('section', 'sg-detail-section'); section.append(el('h3', '', title), content); return section; }
  function factList(entries) { const list = el('dl', 'sg-facts'); entries.forEach(([label, value]) => { list.append(el('dt', '', label), el('dd', '', value === null || value === undefined || value === '' ? 'Não informado' : value)); }); return list; }
  async function openDetail(code) {
    const dialog = $('detailDialog'); $('detailCode').textContent = code; $('detailTitle').textContent = 'Carregando procedimento…';
    $('detailContent').replaceChildren(el('p', '', 'Consultando a ficha da competência selecionada…')); dialog.showModal();
    try {
      const data = await api({ action: 'sigtap_detail', competence: $('competence').value, code });
      const p = data.procedure, area = $('detailContent'); area.replaceChildren();
      $('detailTitle').textContent = p.name;
      area.append(el('p', 'sg-source-line', `Fonte: SIGTAP · competência ${competenceLabel(data.source.competence)} · ${data.source.filename}`));
      if (p.description) area.append(block('Descrição oficial', el('p', '', p.description)));
      area.append(block('Classificação', factList([
        ['Grupo', p.group && `${p.group.code} · ${p.group.label}`], ['Subgrupo', p.subgroup && `${p.subgroup.code} · ${p.subgroup.label}`], ['Forma de organização', p.form && `${p.form.code} · ${p.form.label}`], ['Complexidade', p.complexity?.label], ['Financiamento', p.financing && `${p.financing.code} · ${p.financing.label}`], ['Sexo', p.sex?.label], ['Idade mínima publicada', age(p.ageMin)], ['Idade máxima publicada', age(p.ageMax)]
      ])));
      area.append(block('Valores de referência da tabela', factList([['Ambulatorial · SA', money(p.values?.sa)], ['Hospitalar · SH', money(p.values?.sh)], ['Profissional · SP', money(p.values?.sp)]])));
      const rawEntries = Object.entries(p.attributes || {}).filter(([key, value]) => value !== '' && !['CO_PROCEDIMENTO', 'NO_PROCEDIMENTO', 'DT_COMPETENCIA', 'TP_COMPLEXIDADE', 'TP_SEXO', 'CO_FINANCIAMENTO', 'VL_SH', 'VL_SA', 'VL_SP', 'VL_IDADE_MINIMA', 'VL_IDADE_MAXIMA'].includes(key)).map(([key, value]) => [fieldNames[key] || key, value]);
      if (rawEntries.length) area.append(block('Demais atributos publicados', factList(rawEntries)));
      for (const [kind, rows] of Object.entries(data.relations || {})) {
        if (!rows.length) continue;
        const list = el('ul', 'sg-relation-list');
        rows.forEach(row => { const li = el('li');
          if (kind === 'compatible' && /^\d{10}$/.test(row.code)) { const link = el('button', 'sg-link', `${row.code} · ${row.label}`); link.type = 'button'; link.addEventListener('click', () => openDetail(row.code)); li.append(link); }
          else li.append(el('strong', '', row.code), document.createTextNode(` · ${row.label || 'Descrição não publicada'}`));
          if (row.description) li.append(el('small', '', row.description));
          const attrs = Object.entries(row.attributes || {}).filter(([key, value]) => value !== '' && value !== row.code && !['CO_PROCEDIMENTO', 'DT_COMPETENCIA'].includes(key));
          if (attrs.length) li.append(el('small', '', attrs.map(([key, value]) => `${fieldNames[key] || key}: ${value}`).join(' · ')));
          list.append(li);
        }); area.append(block(`${names[kind] || kind} (${number.format(rows.length)})`, list));
      }
      area.append(el('p', 'sg-caveat', data.notice));
    } catch (error) { $('detailContent').replaceChildren(el('p', 'sg-error', error.message)); }
  }
  async function loadReports() {
    const grid = $('reportGrid'); grid.replaceChildren(el('p', '', 'Calculando distribuição da competência selecionada…'));
    try {
      const data = await api({ action: 'sigtap_aggregates', competence: $('competence').value, filters: filters() });
      source(data.source); $('reportsTotal').textContent = `${number.format(data.total)} procedimentos`; grid.replaceChildren();
      for (const [kind, rows] of Object.entries(data.dimensions)) {
        const card = el('section', 'sg-report-card'); card.append(el('h3', '', names[kind] || kind));
        const max = Math.max(1, ...rows.map(row => row.count));
        rows.slice(0, 15).forEach(row => { const button = el('button', 'sg-report-item'); button.type = 'button';
          const line = el('span', 'sg-report-line'); line.append(el('span', '', `${row.code || '—'} · ${row.label}`), el('strong', '', number.format(row.count)));
          const bar = el('span', 'sg-report-bar'); const fill = el('i'); fill.style.width = `${Math.max(2, row.count / max * 100)}%`; bar.append(fill); button.append(line, bar);
          button.addEventListener('click', () => { const select = document.querySelector(`[data-filter="${kind}"]`); if (select) { if (![...select.options].some(entry => entry.value === row.code)) select.add(option(row.code, `${row.code} · ${row.label}`)); select.value = row.code; } state.page = 1; setView('explore'); loadSearch(); }); card.append(button);
        }); if (!rows.length) card.append(el('p', '', 'Nenhum relacionamento publicado neste recorte.')); grid.append(card);
      }
      const valuesCard = el('section', 'sg-report-card'); valuesCard.append(el('h3', '', 'Valores de referência'));
      valuesCard.append(el('p', '', 'Procedimentos com valor acima de zero em cada componente. A tabela não informa faturamento.'));
      for (const [key, label] of [['sa','Ambulatorial · SA'],['sh','Hospitalar · SH'],['sp','Profissional · SP']]) {
        const item = data.valueStats?.[key]; if (!item) continue;
        const button = el('button', 'sg-value-item', `${label} · ${number.format(item.positive)} procedimento(s) · de ${money(item.minimum)} a ${money(item.maximum)}`);
        button.type = 'button'; button.addEventListener('click', () => { $('valueComponent').value = key; $('minValue').value = '0.01'; state.page = 1; setView('explore'); loadSearch(); });
        valuesCard.append(button);
      }
      grid.append(valuesCard);
    } catch (error) { grid.replaceChildren(el('p', 'sg-error', error.message)); }
  }
  let relationRequest = 0;
  async function loadRelationOptions() {
    const current = ++relationRequest, kind = $('reportRelationKind').value;
    $('reportRelationValue').replaceChildren(option('', 'Escolha um valor'));
    $('reportRelationOpen').disabled = true;
    $('reportRelationStatus').textContent = 'Consultando relacionamentos…';
    try {
      const data = await api({ action:'sigtap_options', competence:$('competence').value, kind, query:$('reportRelationQuery').value.trim() });
      if (current !== relationRequest) return;
      data.options.forEach(item => $('reportRelationValue').add(option(item.code, `${item.code} · ${item.label}`)));
      $('reportRelationStatus').textContent = data.truncated ? 'Mostrando 200 opções. Pesquise por código ou nome para localizar outras.' : `${data.totalOptions} opção(ões) nesta competência.`;
    } catch (error) { if (current === relationRequest) $('reportRelationStatus').textContent = error.message; }
  }
  async function loadCompare() {
    message('compareMessage', 'Comparando duas competências íntegras…');
    try {
      const data = await api({ action: 'sigtap_compare', before: $('compareBefore').value, after: $('compareAfter').value, page: state.comparePage });
      state.compareCount = data.count; message('compareMessage', data.warning || '');
      compareCsvButton.disabled = data.count === 0;
      $('compareSummary').replaceChildren(...[['Incluídos', data.counts.added], ['Excluídos', data.counts.removed], ['Alterados', data.counts.changed]].map(([label, value]) => append(el('div', 'sg-summary-card'), el('small', '', label), el('strong', '', number.format(value)))));
      $('compareRows').replaceChildren(...data.rows.map(row => { const tr = el('tr'); const button = el('button', 'sg-link', row.code); button.type = 'button'; button.addEventListener('click', () => { $('competence').value = row.status === 'removed' ? $('compareBefore').value : $('compareAfter').value; openDetail(row.code); });
        tr.append(append(el('td'), button), el('td', '', { added: 'Incluído', removed: 'Excluído', changed: 'Alterado' }[row.status]), el('td', '', row.afterName || row.beforeName), el('td', '', [row.fieldsChanged?.map(field => fieldNames[field] || field).join(', '), row.relationsChanged ? 'Relacionamentos' : ''].filter(Boolean).join(' · ') || '—')); return tr; }));
      $('comparePageInfo').textContent = `Página ${data.page} de ${Math.max(1, Math.ceil(data.count / data.pageSize))}`;
      $('comparePrevious').disabled = data.page <= 1; $('compareNext').disabled = data.page * data.pageSize >= data.count;
    } catch (error) { compareCsvButton.disabled = true; message('compareMessage', error.message, true); $('compareRows').replaceChildren(); }
  }
  async function exportProcedures() {
    const competence = $('competence').value;
    if (!competence) return;
    procedureCsvButton.disabled = true;
    try {
      const data = await api({action:'sigtap_search', competence, filters:filters(), columnFilters, sort:$('sort').value, direction:$('direction').value, exportAll:true});
      const rows = data.rows.map(item => [item.code, item.name, item.group?.label || '', item.complexity?.label || '', item.financing ? `${item.financing.code} · ${item.financing.label}` : '', csvMoney(item.values?.sa), csvMoney(item.values?.sh), csvMoney(item.values?.sp)]);
      saveCsv(`SPPtab-SIGTAP-procedimentos-${competence}.csv`, ['Código', 'Procedimento', 'Grupo', 'Complexidade', 'Financiamento', 'Valor SA (R$)', 'Valor SH (R$)', 'Valor SP (R$)'], rows);
    } catch (error) { message('message', error.message, true); }
    finally { procedureCsvButton.disabled = state.count === 0; }
  }
  async function exportComparison() {
    const before = $('compareBefore').value, after = $('compareAfter').value;
    if (!before || !after) return;
    compareCsvButton.disabled = true;
    try {
      const data = await api({action:'sigtap_compare', before, after, exportAll:true});
      const rows = data.rows.map(row => [row.code, {added:'Incluído', removed:'Excluído', changed:'Alterado'}[row.status] || row.status, row.afterName || row.beforeName || '', [row.fieldsChanged?.map(field => fieldNames[field] || field).join(', '), row.relationsChanged ? 'Relacionamentos' : ''].filter(Boolean).join(' · ') || '—']);
      saveCsv(`SPPtab-SIGTAP-comparacao-${before}-${after}.csv`, ['Código', 'Alteração', 'Procedimento', 'O que mudou'], rows);
    } catch (error) { message('compareMessage', error.message, true); }
    finally { compareCsvButton.disabled = state.compareCount === 0; }
  }
  async function downloadOfficialZip() {
    const competence = $('competence').value;
    if (!competence) return;
    zipButton.disabled = true;
    zipButton.textContent = 'Preparando ZIP…';
    zipStatus.textContent = '';
    zipStatus.hidden = true;
    try {
      const data = await api({action:'sigtap_zip_prepare', competence});
      const link = el('a'); link.href = data.url; link.download = data.filename;
      document.body.append(link); link.click(); link.remove();
      zipStatus.textContent = `${competenceLabel(competence)} pronto para baixar.`;
      zipStatus.hidden = false;
    } catch (error) { zipStatus.textContent = error.message; zipStatus.hidden = false; }
    finally { zipButton.disabled = false; zipButton.textContent = 'Baixar ZIP oficial'; }
  }
  function refresh() { activeFilters(); if (state.view === 'reports') loadReports(); else if (state.view === 'explore') loadSearch(); }
  async function boot() {
    try {
      const data = await api({ action: 'sigtap_catalog' });
      const competencies = data.competencies || [];
      if (!competencies.length) throw new Error('Nenhuma competência SIGTAP publicada foi encontrada.');
      for (const id of ['competence', 'compareBefore', 'compareAfter']) {
        const select = $(id); select.replaceChildren(...competencies.map(item => option(item.competence, competenceLabel(item.competence))));
      }
      $('competence').value = competencies[0].competence;
      zipButton.disabled = false;
      document.querySelectorAll('.sg-column-trigger').forEach(button => { button.disabled = false; });
      $('compareAfter').value = competencies[0].competence;
      $('compareBefore').value = (competencies[1] || competencies[0]).competence;
      $('sourceStatus').textContent = `Fonte oficial DATASUS · catálogo consultado em ${new Date(data.checkedAt).toLocaleString('pt-BR')}${data.online ? '' : ' · fonte indisponível, usando catálogo local'}`;
      await loadSearch();
      const kinds = ['group', 'subgroup', 'form', 'financing', 'modality', 'registration'];
      await Promise.all(kinds.map(kind => loadOptions(kind).catch(() => {})));
    } catch (error) { message('message', error.message, true); $('sourceStatus').textContent = `SIGTAP · ${error.message}`; $('loader').hidden = true; }
  }
  document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => setView(button.dataset.view)));
  zipButton.addEventListener('click', downloadOfficialZip);
  procedureCsvButton.addEventListener('click', exportProcedures);
  compareCsvButton.addEventListener('click', exportComparison);
  document.querySelectorAll('.sg-column-trigger').forEach(button => { button.disabled = true; button.addEventListener('click', () => openColumnMenu(button)); });
  document.addEventListener('pointerdown', event => { if (columnMenu && !columnMenu.contains(event.target) && !event.target.closest('.sg-column-trigger')) closeColumnMenu(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') closeColumnMenu(); });
  document.querySelectorAll('[data-filter]').forEach(select => select.addEventListener('change', () => { state.page = 1; refresh(); }));
  for (const id of ['filterAge', 'minValue', 'maxValue', 'query']) { let timer; $(id).addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => { state.page = 1; refresh(); }, 350); }); }
  $('valueComponent').addEventListener('change', refresh);
  $('competence').addEventListener('change', async () => { closeColumnMenu(); Object.keys(columnFilters).forEach(key => delete columnFilters[key]); state.page = 1; refresh(); if (state.view === 'reports') loadRelationOptions(); await Promise.all(['group', 'subgroup', 'form', 'financing', 'modality', 'registration'].map(kind => loadOptions(kind).catch(() => {}))); });
  document.querySelectorAll('[data-lookup]').forEach(input => { let timer; input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => loadOptions(input.dataset.lookup, input.value).catch(() => {}), 250); }); input.addEventListener('focus', () => { if (!input.value) loadOptions(input.dataset.lookup).catch(() => {}); }); });
  $('clearFilters').addEventListener('click', () => { document.querySelectorAll('[data-filter]').forEach(node => node.value = ''); document.querySelectorAll('[data-lookup]').forEach(node => node.value = ''); for (const id of ['query', 'filterAge', 'minValue', 'maxValue']) $(id).value = ''; Object.keys(columnFilters).forEach(key => delete columnFilters[key]); closeColumnMenu(); state.page = 1; refresh(); });
  for (const id of ['sort', 'direction', 'pageSize']) $(id).addEventListener('change', () => { state.page = 1; loadSearch(); });
  $('previousPage').addEventListener('click', () => { if (state.page > 1) { state.page--; loadSearch(); } });
  $('nextPage').addEventListener('click', () => { if (state.page * Number($('pageSize').value) < state.count) { state.page++; loadSearch(); } });
  $('runComparison').addEventListener('click', () => { state.comparePage = 1; loadCompare(); });
  $('reportRelationKind').addEventListener('change', () => { $('reportRelationQuery').value = ''; loadRelationOptions(); });
  let relationTimer; $('reportRelationQuery').addEventListener('input', () => { clearTimeout(relationTimer); relationTimer = setTimeout(loadRelationOptions,250); });
  $('reportRelationValue').addEventListener('change', () => { $('reportRelationOpen').disabled = !$('reportRelationValue').value; });
  $('reportRelationOpen').addEventListener('click', () => { const kind = $('reportRelationKind').value, selected = $('reportRelationValue').selectedOptions[0]; if (!selected?.value) return; const select = document.querySelector(`[data-filter="${kind}"]`); if (![...select.options].some(item => item.value === selected.value)) select.add(option(selected.value, selected.textContent)); select.value = selected.value; state.page = 1; setView('explore'); loadSearch(); });
  $('comparePrevious').addEventListener('click', () => { if (state.comparePage > 1) { state.comparePage--; loadCompare(); } });
  $('compareNext').addEventListener('click', () => { if (state.comparePage * 50 < state.compareCount) { state.comparePage++; loadCompare(); } });
  $('closeDetail').addEventListener('click', () => $('detailDialog').close());
  $('detailDialog').addEventListener('click', event => { if (event.target === $('detailDialog')) $('detailDialog').close(); });
  boot();
})();
