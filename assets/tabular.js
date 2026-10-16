(() => {
  'use strict';

  const $ = (selector) => document.querySelector(selector);
  const fileSelect = $('#sourceFile');

  let files = [];
  let libraryRoot = '';
  let selected = null;
  let schema = null;
  let lastResult = null;
  let dbfPath = null;
  let pollTimer = null;
  const categoryRequests = { column: 0, selection: 0 };
  let selectionValues = [];
  let activeFilters = [];
  let tabFiles = [];
  let isTabulating = false;
  let resultPopup = null;
  let resultRunId = '';
  let popupReady = false;
  let pendingPopupMessage = null;

  async function request(payload) {
    const response = await fetch('api.php', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(payload),
    });

    const raw = await response.text();
    let data;
    try {
      data = JSON.parse(raw);
    } catch (_) {
      const status = response.status ? ` (HTTP ${response.status})` : '';
      throw new Error(`O servidor não devolveu uma resposta válida${status}. Tente novamente; se persistir, confira se o servidor local está ativo.`);
    }

    if (!response.ok || !data.ok) {
      throw new Error(data.error || `Não foi possível concluir a operação (HTTP ${response.status}).`);
    }
    return data;
  }

  function notice(stage, message, type = 'info') {
    if (!Number.isInteger(stage)) return;
    const element = document.getElementById(`notice${stage}`);
    if (!element) return;
    element.textContent = message;
    element.className = `notice ${type}`;
    element.hidden = false;
  }

  function setStage(stage) {
    document.querySelectorAll('.stage-panel').forEach((element) => {
      element.hidden = true;
    });
    $(`#stage${stage}`).hidden = false;
    document.querySelectorAll('.wizard-step').forEach((element) => {
      const number = Number(element.dataset.stage);
      element.classList.toggle('active', number === stage);
      element.classList.toggle('complete', number < stage);
    });
    if (stage === 3) loadSchema();
  }

  function formatBytes(value) {
    let number = Number(value) || 0;
    let unit = 0;
    const units = ['B', 'KB', 'MB', 'GB'];
    while (number >= 1024 && unit < units.length - 1) {
      number /= 1024;
      unit += 1;
    }
    return `${number.toLocaleString('pt-BR', { maximumFractionDigits: 1 })} ${units[unit]}`;
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (char) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[char]));
  }

  async function loadCatalog() {
    try {
      const data = await request({ action: 'catalog' });
      files = data.files;
      libraryRoot = data.library_root || '';
      fileSelect.replaceChildren(new Option(files.length ? 'Selecione uma base…' : 'Nenhuma base importada', ''));
      files.forEach((file) => {
        const period = `${String(file.month).padStart(2, '0')}/${file.year}`;
        fileSelect.add(new Option(`${file.system} · ${file.kind} · ${period} · ${file.name} (${formatBytes(file.size)})`, file.path));
      });
      $('#sourceDetails').textContent = files.length
        ? `${files.length.toLocaleString('pt-BR')} ${files.length === 1 ? 'arquivo disponível' : 'arquivos disponíveis'} na biblioteca.`
        : 'Importe primeiro um arquivo na etapa Buscar arquivos.';
    } catch (error) {
      fileSelect.replaceChildren(new Option('Falha ao abrir biblioteca', ''));
      $('#sourceDetails').textContent = error.message;
    }
  }

  function chooseFile() {
    selected = files.find((file) => file.path === fileSelect.value) || null;
    schema = null;
    dbfPath = selected?.dbf_path || null;
    tabFiles = selected ? [selected] : [];
    activeFilters = [];
    $('#toConvert').disabled = !selected;
    $('#sourceDetails').textContent = selected
      ? `${selected.system} · ${selected.kind} · competência ${String(selected.month).padStart(2, '0')}/${selected.year} · ${formatBytes(selected.size)}${selected.converted ? ' · DBF já convertido' : selected.conversion ? ' · conversão em andamento' : ''}`
      : 'Escolha um DBC da biblioteca.';
    $('#notice1').hidden = true;
  }

  function step2() {
    if (!selected) return;
    setStage(2);
    const sourcePath = absoluteLibraryPath(selected.path);
    const destinationRelative = selected.dbf_path || convertedRelativePath(selected.path);
    const destinationPath = absoluteLibraryPath(destinationRelative);
    $('#convertDetails').innerHTML = `<strong>${escapeHtml(selected.name)}</strong> · ${selected.system} ${selected.kind} · ${formatBytes(selected.size)}<div class="convert-paths"><div><span>DBC original</span><code>${escapeHtml(sourcePath)}</code></div><div><span>DBF convertido será salvo em</span><code>${escapeHtml(destinationPath)}</code></div></div>`;
    $('#convertState').hidden = false;
    $('#startConvert').hidden = Boolean(selected.converted);
    $('#startConvert').disabled = false;
    $('#toTabulate').hidden = !selected.converted;

    if (selected.converted) {
      $('#progressLabel').textContent = 'Conversão já concluída';
      $('#progressPercent').textContent = '100%';
      $('#progressFill').style.width = '100%';
      $('#progressCopy').textContent = 'O DBF já está pronto na biblioteca.';
      $('.progress-track').setAttribute('aria-valuenow', '100');
    } else if (selected.conversion?.id) {
      const conversion = selected.conversion;
      const percent = Number(conversion.progress) || 1;
      $('#startConvert').hidden = true;
      $('#progressLabel').textContent = conversion.stage || 'Conversão em andamento';
      $('#progressPercent').textContent = `${percent}%`;
      $('#progressFill').style.width = `${percent}%`;
      $('.progress-track').setAttribute('aria-valuenow', String(percent));
      $('#progressCopy').textContent = conversion.bytes_written
        ? `${conversion.converter === 'rápido' ? 'Conversor rápido · ' : conversion.converter === 'compatibilidade' ? 'Modo de compatibilidade · ' : ''}${formatBytes(conversion.bytes_written)} gravados em ${absoluteLibraryPath(conversion.temporary_path || convertedRelativePath(selected.path) + '.part')}`
        : 'Retomando o acompanhamento desta conversão.';
      pollConversion(conversion.id);
    } else {
      $('#progressLabel').textContent = 'Pronto para converter';
      $('#progressPercent').textContent = '0%';
      $('#progressFill').style.width = '0%';
      $('#progressCopy').textContent = 'O DBF será salvo na biblioteca indicada acima.';
      $('.progress-track').setAttribute('aria-valuenow', '0');
    }
  }

  function convertedRelativePath(source) {
    const parts = String(source).replace(/\\/g, '/').split('/');
    const filename = (parts.pop() || '').replace(/\.dbc$/i, '.dbf');
    return ['CONVERTIDOS', ...parts, filename].join('/');
  }

  function absoluteLibraryPath(relative) {
    const cleanRelative = String(relative).replace(/[\\/]+/g, '\\');
    return libraryRoot ? `${libraryRoot.replace(/[\\/]+$/, '')}\\${cleanRelative}` : cleanRelative;
  }

  async function startConvert() {
    if (!selected) return;
    const button = $('#startConvert');
    button.disabled = true;
    button.textContent = 'Iniciando conversão…';
    $('#convertState').hidden = false;
    $('#progressLabel').textContent = 'Preparando a conversão';
    $('#progressPercent').textContent = '1%';
    $('#progressFill').style.width = '1%';
    $('.progress-track').setAttribute('aria-valuenow', '1');
    $('#progressCopy').textContent = `Aguardando o serviço local · destino: ${absoluteLibraryPath(convertedRelativePath(selected.path))}`;
    notice(2, 'Preparando o arquivo para conversão.');

    try {
      const data = await request({ action: 'convert_start', path: selected.path });
      if (data.done) {
        dbfPath = data.dbf_path;
        selected.converted = true;
        selected.dbf_path = dbfPath;
        step2();
        return;
      }
      localStorage.setItem('tabwin2-job', data.job_id);
      await pollConversion(data.job_id);
    } catch (error) {
      $('#progressLabel').textContent = 'Não foi possível iniciar';
      $('#progressPercent').textContent = '0%';
      $('#progressFill').style.width = '0%';
      $('.progress-track').setAttribute('aria-valuenow', '0');
      $('#progressCopy').textContent = error.message;
      notice(2, error.message, 'error');
      button.disabled = false;
      button.innerHTML = 'Tentar novamente <span aria-hidden="true">↻</span>';
    }
  }

  async function pollConversion(job, failures = 0) {
    clearTimeout(pollTimer);
    try {
      const data = await request({ action: 'convert_status', job_id: job });
      const percent = Number(data.progress) || 0;
      $('#progressLabel').textContent = data.stage || 'Convertendo';
      $('#progressPercent').textContent = `${percent}%`;
      $('#progressFill').style.width = `${percent}%`;
      $('.progress-track').setAttribute('aria-valuenow', String(percent));
      $('#progressCopy').textContent = data.bytes_written
        ? `${data.converter === 'rápido' ? 'Conversor rápido · ' : data.converter === 'compatibilidade' ? 'Modo de compatibilidade · ' : ''}${formatBytes(data.bytes_written)} gravados em ${absoluteLibraryPath(data.temporary_path || (data.dbf_path || convertedRelativePath(selected.path)) + '.part')}`
        : (data.message || 'Aguarde enquanto o arquivo é convertido.');

      if (data.status === 'running') $('#notice2').hidden = true;
      if (data.status === 'done') {
        dbfPath = data.dbf_path;
        selected.converted = true;
        selected.dbf_path = dbfPath;
        localStorage.removeItem('tabwin2-job');
        $('#startConvert').hidden = true;
        $('#toTabulate').hidden = false;
        $('#progressCopy').textContent = `DBF salvo em ${absoluteLibraryPath(data.dbf_path)}. Você já pode avançar para a tabulação.`;
        notice(2, 'Conversão concluída com sucesso.', 'success');
        return;
      }
      if (data.status === 'error') {
        localStorage.removeItem('tabwin2-job');
        $('#progressLabel').textContent = data.stage || 'Não foi possível converter';
        $('#progressCopy').textContent = data.message || 'Falha na conversão. Tente novamente.';
        notice(2, data.message || 'Falha na conversão.', 'error');
        $('#startConvert').hidden = false;
        $('#startConvert').disabled = false;
        return;
      }
      pollTimer = setTimeout(() => pollConversion(job), 700);
    } catch (error) {
      if (failures < 2) {
        pollTimer = setTimeout(() => pollConversion(job, failures + 1), 1500);
        return;
      }
      $('#progressLabel').textContent = 'Sem comunicação com o serviço local';
      $('#progressCopy').textContent = 'Confira se o SPPtab continua em execução. A conversão pode ter continuado; abra novamente e consulte o arquivo na biblioteca.';
      notice(2, `${error.message} A conversão continua salva; tente consultar novamente.`, 'error');
      $('#startConvert').disabled = false;
    }
  }

  function optionList(select, items, placeholder, selectFirst = false) {
    select.replaceChildren();
    if (placeholder) select.add(new Option(placeholder, ''));
    items.forEach((item) => {
      const option = new Option(`${item.label} · ${item.field}`, item.id);
      option.dataset.search = `${item.label} ${item.field}`.toLocaleLowerCase('pt-BR');
      select.add(option);
    });
    if (selectFirst && items.length) select.selectedIndex = placeholder ? 1 : 0;
  }

  function lineOptionsForSelectedState(items) {
    const stateNames = {
      AC: 'Acre', AL: 'Alagoas', AP: 'Amapá', AM: 'Amazonas', BA: 'Bahia', CE: 'Ceará', DF: 'Distrito Federal',
      ES: 'Espírito Santo', GO: 'Goiás', MA: 'Maranhão', MT: 'Mato Grosso', MS: 'Mato Grosso do Sul', MG: 'Minas Gerais',
      PA: 'Pará', PB: 'Paraíba', PR: 'Paraná', PE: 'Pernambuco', PI: 'Piauí', RJ: 'Rio de Janeiro', RN: 'Rio Grande do Norte',
      RS: 'Rio Grande do Sul', RO: 'Rondônia', RR: 'Roraima', SC: 'Santa Catarina', SP: 'São Paulo', SE: 'Sergipe', TO: 'Tocantins',
    };
    const filename = String(selected?.name || '').toUpperCase();
    const fileMatch = filename.match(/^[A-Z]{2}([A-Z]{2})\d{4}(?=\.|$)/);
    const stateCode = fileMatch?.[1];
    const stateName = stateNames[stateCode];
    if (!stateName) return items;

    const establishment = /^Estabelecimentos\s+(CNES|CNPJ\/CPF)-([A-Z]{2})$/i;
    const filtered = items.flatMap((item) => {
      const match = item.label.match(establishment);
      if (!match) return [item];
      if (match[2].toUpperCase() !== stateCode) return [];
      const kind = match[1].toUpperCase() === 'CNES' ? 'CNES' : 'CNPJ/CPF';
      return [{ ...item, label: `Estabelecimentos · ${kind} (${stateName})` }];
    });
    return filtered.length ? filtered : items;
  }

  function filterOptionList(select, query, status) {
    const term = query.trim().toLocaleLowerCase('pt-BR');
    let visible = 0;
    Array.from(select.options).forEach((option) => {
      if (!option.value) {
        option.hidden = false;
        return;
      }
      const matches = !term || (option.dataset.search || option.textContent.toLocaleLowerCase('pt-BR')).includes(term);
      option.hidden = !matches;
      if (matches) visible += 1;
    });

    const selected = select.value ? select.selectedOptions[0]?.textContent.trim() : '';
    const selectionNote = selected && select.selectedOptions[0]?.hidden ? ` Selecionada: ${selected}.` : '';
    status.textContent = visible
      ? `${visible.toLocaleString('pt-BR')} ${visible === 1 ? 'opção disponível' : 'opções disponíveis'}.${selectionNote}`
      : `Nenhuma opção encontrada. Tente outro termo.${selectionNote}`;
  }

  function metricChoices() {
    const result = [{
      id: 'FREQ',
      label: schema.groupField ? `Frequência · ${schema.groupField.field}` : 'Frequência de registros',
      field: schema.groupField?.field || '',
    }, { id: 'RECORDS', label: 'Número de registros', field: '' }];
    schema.increments.forEach((item) => result.push({ id: item.field, label: item.label, field: item.field }));
    const seen = new Set();
    return result.filter((item) => {
      if (seen.has(item.id)) return false;
      seen.add(item.id);
      return true;
    }).slice(0, 50);
  }

  function selectedMetrics() {
    return Array.from(document.querySelectorAll('#incrementOptions input:checked')).map((input) => input.value);
  }

  function updateRunButton() {
    $('#runButton').disabled = isTabulating || !schema?.lineOptions.length || !$('#rowField').value || !selectedMetrics().length;
  }

  function renderIncrements() {
    const box = $('#incrementOptions');
    box.replaceChildren();
    metricChoices().forEach((item, index) => {
      const label = document.createElement('label');
      label.className = 'increment-option';
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.value = item.id;
      input.checked = index === 0;
      const copy = document.createElement('span');
      copy.textContent = item.label;
      if (item.field) {
        const code = document.createElement('small');
        code.textContent = item.field;
        copy.append(code);
      }
      label.append(input, copy);
      box.append(label);
    });
    updateMetricRules();
  }

  function updateMetricRules() {
    const metrics = selectedMetrics();
    const multi = metrics.length > 1;
    $('#incrementCount').textContent = `${metrics.length} ${metrics.length === 1 ? 'selecionado' : 'selecionados'}`;
    const column = $('#columnField');
    if (multi && column.value) {
      column.value = '';
      loadColumnValues();
    }
    column.disabled = multi;
    column.title = multi ? 'Com mais de um incremento, mantenha Colunas como Não ativa.' : '';
    $('#columnValueFilter').hidden = multi || !column.value;
    updateRunButton();
  }

  async function loadCategoryValues(option, select, status) {
    const requestId = ++categoryRequests.column;
    select.replaceChildren(new Option('Todas as categorias', ''));
    select.disabled = true;
    if (!option) {
      status.textContent = 'Escolha uma coluna para carregar as categorias disponíveis.';
      return null;
    }

    status.textContent = 'Carregando categorias da base…';
    try {
      const data = await request({
        action: 'category_values',
        path: selected.path,
        dbfPath,
        option,
        optionType: 'column',
        belem: $('#belemFilter').checked,
      });
      if (requestId !== categoryRequests.column) return null;
      data.values.forEach((item) => {
        const label = item.label && item.label !== item.value ? `${item.label} · código ${item.value}` : item.value;
        select.add(new Option(label, item.value));
      });
      select.disabled = false;
      const count = data.values.length.toLocaleString('pt-BR');
      status.textContent = data.truncated
        ? `Exibindo os primeiros ${count} valores disponíveis.`
        : `${count} ${data.values.length === 1 ? 'categoria disponível' : 'categorias disponíveis'}.`;
      return data.values;
    } catch (error) {
      if (requestId === categoryRequests.column) status.textContent = error.message;
      return null;
    }
  }

  function loadColumnValues() {
    const option = $('#columnField').value;
    const select = $('#columnValue');
    const wrapper = $('#columnValueFilter');
    if (!option || selectedMetrics().length > 1) {
      categoryRequests.column += 1;
      wrapper.hidden = true;
      select.replaceChildren(new Option('Todas as categorias', ''));
      select.disabled = true;
      return;
    }
    wrapper.hidden = false;
    loadCategoryValues(option, select, $('#columnValuesStatus'));
  }

  function renderFilterValues() {
    const list = $('#filterValue');
    const search = $('#filterSearch').value.trim().toLocaleLowerCase('pt-BR');
    let filtered = 0;
    const selected = new Set(Array.from(list.querySelectorAll('input:checked')).map((input) => input.value));
    list.replaceChildren();
    selectionValues.forEach((item) => {
      const row = document.createElement('label');
      row.className = 'category-option';
      row.dataset.search = `${item.label} ${item.value}`.toLocaleLowerCase('pt-BR');
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.value = item.value;
      checkbox.checked = selected.has(item.value);
      checkbox.addEventListener('change', updateFilterButton);
      const label = document.createElement('span');
      label.textContent = item.label;
      row.append(checkbox, label);
      row.hidden = Boolean(search && !row.dataset.search.includes(search));
      if (!row.hidden) filtered += 1;
      list.append(row);
    });
    list.setAttribute('aria-disabled', selectionValues.length ? 'false' : 'true');
    if (search) {
      $('#filterStatus').textContent = filtered
        ? `${filtered.toLocaleString('pt-BR')} categorias encontradas.`
        : 'Nenhuma categoria encontrada. Tente outro termo.';
    }
    updateFilterButton();
  }

  async function loadSelectionValues() {
    const optionId = $('#filterField').value;
    const search = $('#filterSearch');
    const list = $('#filterValue');
    const status = $('#filterStatus');
    selectionValues = [];

    if (!optionId) {
      categoryRequests.selection += 1;
      search.value = '';
      search.disabled = true;
      list.replaceChildren();
      list.setAttribute('aria-disabled', 'true');
      status.textContent = 'Escolha uma informação para ver os valores disponíveis.';
      updateFilterButton();
      return;
    }

    search.value = '';
    search.disabled = true;
    list.replaceChildren();
    list.setAttribute('aria-disabled', 'true');
    updateFilterButton();
    const requestId = ++categoryRequests.selection;
    status.textContent = 'Carregando categorias da base…';
    try {
      const data = await request({
        action: 'category_values',
        path: selected.path,
        dbfPath,
        option: optionId,
        optionType: 'selection',
        belem: $('#belemFilter').checked,
      });
      if (requestId !== categoryRequests.selection || $('#filterField').value !== optionId) return;
      selectionValues = data.values.map((item) => ({
        value: String(item.value),
        label: item.label && item.label !== item.value ? `${item.label} · código ${item.value}` : String(item.value),
      }));
      renderFilterValues();
      const count = selectionValues.length.toLocaleString('pt-BR');
      status.textContent = data.truncated
        ? `Exibindo as primeiras ${count} categorias disponíveis.`
        : `${count} ${selectionValues.length === 1 ? 'categoria disponível' : 'categorias disponíveis'}.`;
    } catch (error) {
      if (requestId === categoryRequests.selection) status.textContent = error.message;
      updateFilterButton();
    }
    search.disabled = false;
  }

  function updateFilterButton() {
    const hasSelection = Boolean($('#filterValue').querySelector('input:checked'));
    $('#includeSelection').disabled = !hasSelection;
    $('#excludeSelection').disabled = !hasSelection;
    $('#locateCategory').disabled = !$('#filterField').value;
  }

  function drawFilters() {
    const box = $('#activeFilters');
    box.replaceChildren();
    activeFilters.forEach((filter, index) => {
      const item = document.createElement('div');
      item.className = `filter-item${filter.mode === 'exclude' ? ' exclude' : ''}`;
      const action = document.createElement('span');
      action.className = 'filter-action';
      action.textContent = filter.mode === 'exclude' ? 'Excluir' : 'Incluir';
      const copy = document.createElement('span');
      copy.className = 'filter-copy';
      const field = document.createElement('strong');
      field.textContent = filter.label;
      const category = document.createElement('small');
      category.textContent = filter.categoryLabel;
      copy.append(field, category);

      const remove = document.createElement('button');
      remove.type = 'button';
      remove.setAttribute('aria-label', `Remover filtro ${filter.label}: ${filter.categoryLabel}`);
      remove.textContent = 'Remover';
      remove.addEventListener('click', () => {
        activeFilters.splice(index, 1);
        drawFilters();
        $('#filterStatus').textContent = 'Seleção removida. Confira as regras que continuam ativas.';
      });
      item.append(action, copy, remove);
      box.append(item);
    });
    const count = activeFilters.length;
    $('#filterCount').textContent = count
      ? `${count} ${count === 1 ? 'categoria' : 'categorias'}`
      : 'Nenhuma';
  }

  function addFilter(mode) {
    const option = schema?.selectionOptions.find((item) => item.id === $('#filterField').value);
    const chosen = Array.from($('#filterValue').querySelectorAll('input:checked'));
    if (!option || !chosen.length) return;
    let added = 0;
    for (const item of chosen) {
      if (activeFilters.some((filter) => filter.option === option.id && filter.value === item.value && filter.mode === mode)) {
        item.checked = false;
        continue;
      }
      if (activeFilters.length >= 300) {
        notice(3, 'O limite é de 300 categorias selecionadas por tabulação.', 'error');
        break;
      }
      activeFilters.push({
        option: option.id,
        field: option.field,
        label: option.label,
        value: item.value,
        categoryLabel: item.closest('.category-option')?.querySelector('span')?.textContent || item.value,
        mode,
      });
      item.checked = false;
      added += 1;
    }
    drawFilters();
    updateFilterButton();
    if (added) {
      $('#filterStatus').textContent = `${added} ${added === 1 ? 'categoria adicionada' : 'categorias adicionadas'} como ${mode === 'exclude' ? 'exclusão' : 'inclusão'}.`;
      $('#filterSearch').focus();
    }
  }

  function locateCategory() {
    if (!$('#filterField').value) return;
    if (!selectionValues.length) {
      loadSelectionValues().then(() => $('#filterSearch').focus());
      return;
    }
    renderFilterValues();
    $('#filterSearch').focus();
  }

  function renderFiles() {
    const select = $('#extraFile');
    const compatible = files.filter((file) => file.converted
      && selected
      && file.system === selected.system
      && file.kind === selected.kind
      && !tabFiles.some((chosen) => chosen.path === file.path));

    select.replaceChildren(new Option(
      compatible.length ? 'Escolha outra competência…' : 'Nenhuma outra base convertida disponível',
      '',
    ));
    compatible.forEach((file) => {
      const period = `${String(file.month).padStart(2, '0')}/${file.year}`;
      select.add(new Option(`${period} · ${file.name} · ${formatBytes(file.size)}`, file.path));
    });
    select.disabled = compatible.length === 0;
    $('#addFile').disabled = !select.value || compatible.length === 0;
    $('#fileCount').textContent = `${tabFiles.length} ${tabFiles.length === 1 ? 'base selecionada' : 'bases selecionadas'}`;
    $('#fileStatus').textContent = compatible.length
      ? 'Confira se as bases têm a mesma estrutura; o sistema verifica isso antes de tabular.'
      : `Nenhuma outra base ${selected ? `${selected.system} · ${selected.kind}` : ''} convertida está disponível.`;

    const box = $('#selectedFiles');
    box.replaceChildren();
    tabFiles.forEach((file) => {
      const item = document.createElement('div');
      item.className = 'selected-file';
      const copy = document.createElement('span');
      copy.className = 'selected-file-copy';
      const name = document.createElement('strong');
      name.textContent = file.name;
      const period = document.createElement('small');
      period.textContent = `${String(file.month).padStart(2, '0')}/${file.year} · ${file.kind}${file.path === selected?.path ? ' · base principal' : ''}`;
      copy.append(name, period);

      const remove = document.createElement('button');
      remove.type = 'button';
      remove.textContent = '×';
      remove.disabled = file.path === selected?.path;
      remove.setAttribute('aria-label', file.path === selected?.path ? 'Base principal' : `Remover ${file.name}`);
      remove.addEventListener('click', () => {
        tabFiles = tabFiles.filter((itemFile) => itemFile.path !== file.path);
        renderFiles();
      });
      item.append(copy, remove);
      box.append(item);
    });
  }

  function addFile() {
    const file = files.find((item) => item.path === $('#extraFile').value);
    if (!file || tabFiles.some((item) => item.path === file.path)) return;
    tabFiles.push(file);
    renderFiles();
  }

  async function loadSchema() {
    if (!selected) return;
    if (schema && schema.file?.path === selected.path) return;

    $('#definitionStatus').textContent = 'Consultando o arquivo convertido e a definição oficial…';
    $('#tabControls').hidden = true;
    $('#runButton').disabled = true;
    $('#advancedOptions').hidden = true;
    $('#filterOptions').hidden = true;
    $('#fileOptions').hidden = true;
    $('#columnValueFilter').hidden = true;
    $('#resultPanel').hidden = true;
    try {
      schema = await request({ action: 'schema', path: selected.path });
      dbfPath = schema.dbfPath;
      $('#definitionStatus').innerHTML = `<strong>${escapeHtml(schema.definition.name)}</strong> · ${Number(schema.recordCount).toLocaleString('pt-BR')} registros · ${schema.fields.length} campos compatíveis`;
      $('#rowSearch').value = '';
      $('#columnSearch').value = '';
      optionList($('#rowField'), lineOptionsForSelectedState(schema.lineOptions), '', true);
      filterOptionList($('#rowField'), $('#rowSearch').value, $('#rowListStatus'));
      optionList($('#columnField'), schema.columnOptions, 'Não ativa');
      filterOptionList($('#columnField'), $('#columnSearch').value, $('#columnListStatus'));
      renderIncrements();
      $('#tabControls').hidden = false;
      $('#incrementSection').hidden = false;
      $('#advancedOptions').hidden = false;
      $('#filterField').replaceChildren(new Option('Escolha uma informação…', ''));
      schema.selectionOptions.forEach((item) => {
        $('#filterField').add(new Option(`${item.label} · ${item.field}`, item.id));
      });
      $('#filterField').disabled = !schema.selectionOptions.length;
      $('#filterOptions').hidden = !schema.selectionOptions.length;
      $('#filterSearch').value = '';
      $('#filterSearch').disabled = true;
      $('#filterValue').replaceChildren();
      $('#filterValue').setAttribute('aria-disabled', 'true');
      $('#filterStatus').textContent = 'Escolha uma informação para ver os valores disponíveis.';
      selectionValues = [];
      activeFilters = [];
      categoryRequests.selection += 1;
      drawFilters();
      tabFiles = selected ? [selected] : [];
      renderFiles();
      $('#fileOptions').hidden = false;
      $('#municipalityWrap').hidden = !schema.municipalityField;
      if (schema.municipalityField) {
        $('#municipalityDescription').textContent = `Belém · código IBGE 150140 · campo ${schema.municipalityField}`;
      }
      loadColumnValues();
      updateRunButton();
      if (!schema.lineOptions.length) {
        notice(3, 'A definição não encontrou opções de linha compatíveis com os campos desta base.', 'error');
      } else {
        $('#notice3').hidden = true;
      }
    } catch (error) {
      schema = null;
      $('#definitionStatus').textContent = 'Não foi possível carregar a definição.';
      notice(3, error.message, 'error');
    }
  }

  function sendPopupMessage() {
    if (!resultPopup || resultPopup.closed || !popupReady || !pendingPopupMessage) return;
    resultPopup.postMessage(pendingPopupMessage, location.origin);
    pendingPopupMessage = null;
  }

  window.addEventListener('message', (event) => {
    if (event.origin !== location.origin || event.source !== resultPopup) return;
    const message = event.data || {};
    if (message.type === 'tabwin2-result-ready' && message.runId === resultRunId) {
      popupReady = true;
      sendPopupMessage();
    }
  });

  function startPopup() {
    resultRunId = Array.from(crypto.getRandomValues(new Uint8Array(16)))
      .map((value) => value.toString(16).padStart(2, '0')).join('');
    popupReady = false;
    pendingPopupMessage = null;
    resultPopup = window.open(`resultado.php?run=${resultRunId}`, 'tabwin2-result');
    return resultPopup;
  }

  async function generate() {
    if (!schema || !$('#rowField').value || !selectedMetrics().length || isTabulating) return;

    const popup = startPopup();
    const button = $('#runButton');
    isTabulating = true;
    updateRunButton();
    button.textContent = 'Tabulando…';
    notice(3, 'Lendo a base e cruzando as categorias.');

    const column = $('#columnField').value;
    const columnValue = $('#columnValue').value;
    try {
      lastResult = await request({
        action: 'tabulate',
        path: selected.path,
        dbfPath,
        sources: tabFiles.map((file) => ({ path: file.path, dbfPath: file.dbf_path })),
        row: $('#rowField').value,
        column,
        metrics: selectedMetrics(),
        belem: $('#belemFilter').checked,
        filters: activeFilters.map((filter) => ({ option: filter.option, value: filter.value, mode: filter.mode })),
        columnFilter: column && columnValue ? { option: column, value: columnValue } : null,
        suppressRows: $('#suppressRows').checked,
        suppressColumns: $('#suppressColumns').checked,
        testCrc: $('#testCrc').checked,
        saveRecords: $('#saveRecords').checked,
        unclassified: document.querySelector('input[name="unclassified"]:checked')?.value || 'ignore',
      });

      if (popup && !popup.closed) {
        pendingPopupMessage = { type: 'tabwin2-result', runId: resultRunId, data: lastResult };
        sendPopupMessage();
      } else {
        drawResult(lastResult);
      }
      notice(3, popup && !popup.closed
        ? 'Tabulação concluída. O resultado está na nova aba.'
        : 'Tabulação concluída. O resultado ficou nesta página porque a nova aba foi bloqueada.', 'success');
    } catch (error) {
      if (popup && !popup.closed) {
        pendingPopupMessage = { type: 'tabwin2-error', runId: resultRunId, message: error.message };
        sendPopupMessage();
      }
      notice(3, error.message, 'error');
    } finally {
      isTabulating = false;
      button.innerHTML = 'Gerar tabulação <span aria-hidden="true">↗</span>';
      updateRunButton();
    }
  }

  function drawResult(data) {
    const head = $('#resultHead');
    const body = $('#resultBody');
    const foot = $('#resultFoot');
    head.replaceChildren();
    body.replaceChildren();
    foot.replaceChildren();

    const metrics = data.metrics || [];
    const showTotal = metrics.length === 1 && ((data.columns || []).length > 1 || data.columns[0] !== 'Total');
    const header = ['Linha', ...data.columns];
    if (showTotal) header.push('Total da linha');
    const headerRow = document.createElement('tr');
    header.forEach((value) => {
      const th = document.createElement('th');
      th.textContent = value;
      headerRow.append(th);
    });
    head.append(headerRow);

    data.rows.forEach((row) => {
      const tr = document.createElement('tr');
      const label = document.createElement('td');
      label.textContent = row.label;
      tr.append(label);
      row.values.forEach((value) => {
        const td = document.createElement('td');
        td.textContent = Number(value).toLocaleString('pt-BR', { maximumFractionDigits: 4 });
        tr.append(td);
      });
      if (showTotal) {
        const td = document.createElement('td');
        td.textContent = Number(row.total).toLocaleString('pt-BR', { maximumFractionDigits: 4 });
        tr.append(td);
      }
      body.append(tr);
    });

    const totalRow = document.createElement('tr');
    const totalLabel = document.createElement('th');
    totalLabel.textContent = 'Total geral';
    totalRow.append(totalLabel);
    data.columnTotals.forEach((value) => {
      const td = document.createElement('td');
      td.textContent = Number(value).toLocaleString('pt-BR', { maximumFractionDigits: 4 });
      totalRow.append(td);
    });
    if (showTotal) {
      const td = document.createElement('td');
      td.textContent = Number(data.total).toLocaleString('pt-BR', { maximumFractionDigits: 4 });
      totalRow.append(td);
    }
    foot.append(totalRow);
    $('#resultCount').textContent = data.rows.length.toLocaleString('pt-BR');
    $('#resultSummary').textContent = `${data.metric} · ${data.records.toLocaleString('pt-BR')} registros incluídos · ${data.processedRecords.toLocaleString('pt-BR')} registros lidos${data.truncated ? ` · exibindo ${data.rows.length.toLocaleString('pt-BR')} de ${data.totalCategories.toLocaleString('pt-BR')} categorias` : ''}`;
    $('#resultPanel').hidden = false;
  }

  function exportCsv() {
    if (!lastResult) return;
    const showTotal = (lastResult.metrics || []).length === 1
      && ((lastResult.columns || []).length > 1 || lastResult.columns[0] !== 'Total');
    const rows = [
      ['Linha', ...lastResult.columns, ...(showTotal ? ['Total da linha'] : [])],
      ...lastResult.rows.map((row) => [row.label, ...row.values, ...(showTotal ? [row.total] : [])]),
      ['Total geral', ...lastResult.columnTotals, ...(showTotal ? [lastResult.total] : [])],
    ];
    const csv = `\ufeff${rows.map((row) => row.map((value) => `"${String(value).replace(/"/g, '""')}"`).join(';')).join('\r\n')}`;
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'tabulacao-spptab.csv';
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  fileSelect.addEventListener('change', chooseFile);
  $('#toConvert').addEventListener('click', step2);
  $('#startConvert').addEventListener('click', startConvert);
  $('#toTabulate').addEventListener('click', () => setStage(3));
  $('#rowSearch').addEventListener('input', () => filterOptionList($('#rowField'), $('#rowSearch').value, $('#rowListStatus')));
  $('#columnSearch').addEventListener('input', () => filterOptionList($('#columnField'), $('#columnSearch').value, $('#columnListStatus')));
  $('#rowField').addEventListener('change', updateRunButton);
  $('#columnField').addEventListener('change', loadColumnValues);
  $('#columnValue').addEventListener('change', updateRunButton);
  $('#belemFilter').addEventListener('change', () => {
    loadColumnValues();
    if ($('#filterField').value) loadSelectionValues();
  });
  $('#incrementOptions').addEventListener('change', updateMetricRules);
  $('#filterField').addEventListener('change', loadSelectionValues);
  $('#filterSearch').addEventListener('input', renderFilterValues);
  $('#filterValue').addEventListener('change', updateFilterButton);
  $('#locateCategory').addEventListener('click', locateCategory);
  $('#includeSelection').addEventListener('click', () => addFilter('include'));
  $('#excludeSelection').addEventListener('click', () => addFilter('exclude'));
  $('#extraFile').addEventListener('change', () => {
    $('#addFile').disabled = !$('#extraFile').value;
  });
  $('#addFile').addEventListener('click', addFile);
  $('#runButton').addEventListener('click', generate);
  $('#exportCsv').addEventListener('click', exportCsv);
  document.querySelectorAll('.wizard-step').forEach((button) => {
    button.addEventListener('click', () => {
      const stage = Number(button.dataset.stage);
      if (stage === 1) setStage(1);
      if (stage === 2 && selected) step2();
      if (stage === 3 && selected?.converted) setStage(3);
    });
  });

  loadCatalog().then(() => {
    const job = localStorage.getItem('tabwin2-job');
    if (!job || fileSelect.options.length <= 1) return;
    const match = files.find((file) => file.conversion?.id === job) || files.find((file) => !file.converted);
    if (!match) return;
    selected = match;
    fileSelect.value = match.path;
    step2();
    if (match.conversion?.id !== job) {
      $('#startConvert').hidden = true;
      pollConversion(job);
    }
  });
})();
