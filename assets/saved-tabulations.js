(() => {
  'use strict';

  const $ = (selector) => document.querySelector(selector);
  const ACTIVE_FILE_KEY = 'spptab-active-file-v1';
  const PENDING_PRESET_KEY = 'spptab-pending-preset-v1';
  const fileSelect = $('#presetSource');
  let files = [];
  let activeFile = null;
  let requestNumber = 0;

  async function request(payload) {
    const response = await fetch('api.php', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(payload),
    });
    const raw = await response.text();
    let data;
    try { data = JSON.parse(raw); }
    catch (_) { throw new Error(`O serviço local não retornou uma resposta válida${response.status ? ` (HTTP ${response.status})` : ''}.`); }
    if (!response.ok || !data.ok) throw new Error(data.error || `Não foi possível consultar as combinações (HTTP ${response.status}).`);
    return data;
  }

  function formatDate(timestamp) {
    const date = new Date(Number(timestamp || 0) * 1000);
    if (Number.isNaN(date.getTime())) return 'Data não informada';
    return new Intl.DateTimeFormat('pt-BR', { day: 'numeric', month: 'long', year: 'numeric' }).format(date);
  }

  function period(file) {
    return `${String(file.month).padStart(2, '0')}/${file.year}`;
  }

  function setNotice(message, isError = false) {
    const notice = $('#presetPageNotice');
    notice.textContent = message;
    notice.classList.toggle('is-error', isError);
    notice.hidden = false;
  }

  function setInfo(message, isError = false) {
    const info = $('#presetSourceInfo');
    info.textContent = message;
    info.classList.toggle('is-error', isError);
  }

  function addChip(parent, title, text) {
    const chip = document.createElement('span');
    chip.className = 'preset-chip';
    const strong = document.createElement('strong');
    strong.textContent = `${title}:`;
    const value = document.createElement('span');
    value.textContent = text;
    chip.append(strong, value);
    parent.append(chip);
  }

  function createPresetCard(preset) {
    const card = document.createElement('article');
    card.className = 'preset-card';

    const main = document.createElement('div');
    main.className = 'preset-card-main';
    const titleRow = document.createElement('div');
    titleRow.className = 'preset-card-title-row';
    const title = document.createElement('h3');
    title.className = 'preset-card-title';
    title.textContent = preset.name || 'Combinação sem nome';
    const family = document.createElement('span');
    family.className = 'preset-family';
    family.textContent = `${preset.system || activeFile.system} · ${preset.kind || activeFile.kind} · ${preset.uf || activeFile.uf}`;
    titleRow.append(title, family);
    const meta = document.createElement('p');
    meta.className = 'preset-card-meta';
    meta.textContent = `Salva em ${formatDate(preset.createdAt)} · definição ${preset.definition || 'oficial'}`;
    const summary = document.createElement('div');
    summary.className = 'preset-card-summary';
    addChip(summary, 'Linha', preset.rowLabel || 'Configuração salva');
    addChip(summary, 'Coluna', preset.columnLabel || 'Não ativa');
    const metrics = Array.isArray(preset.metricLabels) ? preset.metricLabels.join(' · ') : 'Medidas salvas';
    addChip(summary, 'Medidas', metrics);
    if (Number(preset.filterCount)) addChip(summary, 'Seleções', `${Number(preset.filterCount)} categoria(s)`);
    main.append(titleRow, meta, summary);

    const actions = document.createElement('div');
    actions.className = 'preset-card-actions';
    const use = document.createElement('button');
    use.className = 'button button-primary';
    use.type = 'button';
    use.innerHTML = `${activeFile.converted ? 'Usar nesta competência' : 'Preparar e aplicar'} <span aria-hidden="true">→</span>`;
    use.addEventListener('click', () => usePreset(preset.id));
    const remove = document.createElement('button');
    remove.className = 'preset-delete';
    remove.type = 'button';
    remove.textContent = '×';
    remove.setAttribute('aria-label', `Remover combinação ${preset.name || ''}`);
    remove.title = 'Remover combinação';
    remove.addEventListener('click', () => removePreset(preset.id, preset.name || 'esta combinação', card, remove));
    actions.append(use, remove);
    card.append(main, actions);
    return card;
  }

  function updateTabularLinks(file) {
    const url = file?.path
      ? `tabular.php?stage=3&file=${encodeURIComponent(file.path)}`
      : 'tabular.php?stage=3';
    $('#createPresetLink').href = url;
    $('#presetEmptyAction').href = url;
    $('#createPresetLink').hidden = !file;
  }

  function renderEmpty(title, copy) {
    $('#presetEmptyTitle').textContent = title;
    $('#presetEmptyCopy').textContent = copy;
    $('#presetLoading').hidden = true;
    $('#presetCards').replaceChildren();
    $('#presetEmpty').hidden = false;
    $('#presetCount').textContent = '0';
  }

  async function loadPresets() {
    const currentRequest = ++requestNumber;
    $('#presetPageNotice').hidden = true;
    $('#presetCards').replaceChildren();
    $('#presetEmpty').hidden = true;
    $('#presetLoading').hidden = false;
    if (!activeFile) {
      $('#presetLoading').hidden = true;
      $('#presetCount').textContent = '0';
      setInfo('Selecione um DBC da biblioteca para consultar as combinações compatíveis.');
      renderEmpty('Selecione uma base para começar', 'Depois de escolher o DBC, mostraremos as combinações que podem ser aplicadas a ele.');
      return;
    }
    setInfo(`${activeFile.system} · ${activeFile.kind} · ${activeFile.uf} · competência ${period(activeFile)} · ${activeFile.name}. A lista considera o mesmo estado, estrutura e definição.`);
    $('#selectedFileTag').textContent = `${activeFile.uf} · ${period(activeFile)}`;
    updateTabularLinks(activeFile);
    try {
      const data = await request({ action: 'preset_list', path: activeFile.path });
      if (currentRequest !== requestNumber) return;
      const presets = Array.isArray(data.presets) ? data.presets : [];
      $('#presetLoading').hidden = true;
      $('#presetCount').textContent = String(presets.length);
      $('#presetListDescription').textContent = presets.length
        ? `Modelos compatíveis com ${data.file.name} · ${data.definition || 'definição oficial'}`
        : 'Nenhuma combinação compatível foi salva para esta estrutura.';
      if (!presets.length) {
        renderEmpty('Ainda não há combinações para esta estrutura', 'Monte uma tabulação, salve as opções e depois escolha outra competência compatível para reaproveitá-la.');
        return;
      }
      $('#presetEmpty').hidden = true;
      presets.forEach((preset) => $('#presetCards').append(createPresetCard(preset)));
    } catch (error) {
      if (currentRequest !== requestNumber) return;
      $('#presetLoading').hidden = true;
      setInfo(error.message, true);
      renderEmpty('Não foi possível carregar as combinações', 'Confira se o serviço local do SPPtab está ativo e tente novamente.');
      setNotice(error.message, true);
    }
  }

  async function usePreset(id) {
    if (!activeFile || !id) return;
    try {
      localStorage.setItem(ACTIVE_FILE_KEY, activeFile.path);
      localStorage.setItem(PENDING_PRESET_KEY, id);
      window.location.href = 'tabular.php?aplicar=1';
    } catch (_) {
      setNotice('O navegador não conseguiu guardar a combinação para abrir na tela de tabulação. Confira as permissões de armazenamento do site.', true);
    }
  }

  async function removePreset(id, name, card, button) {
    if (!activeFile || !window.confirm(`Remover a combinação “${name}”?`)) return;
    button.disabled = true;
    try {
      await request({ action: 'preset_delete', path: activeFile.path, preset_id: id });
      card.remove();
      const count = Math.max(0, Number($('#presetCount').textContent) - 1);
      $('#presetCount').textContent = String(count);
      if (!count) renderEmpty('Ainda não há combinações para esta estrutura', 'Monte uma tabulação, salve as opções e depois escolha outra competência compatível para reaproveitá-la.');
      setNotice(`“${name}” foi removida deste computador.`);
    } catch (error) {
      button.disabled = false;
      setNotice(error.message, true);
    }
  }

  function chooseFile(path, persist = true) {
    activeFile = files.find((file) => file.path === path) || null;
    if (persist) {
      try {
        if (activeFile) localStorage.setItem(ACTIVE_FILE_KEY, activeFile.path);
        else localStorage.removeItem(ACTIVE_FILE_KEY);
      } catch (_) {}
      window.dispatchEvent(new Event('spptab-active-file-change'));
    }
    if (activeFile) $('#selectedFileTag').textContent = `${activeFile.uf} · ${period(activeFile)}`;
    else $('#selectedFileTag').textContent = 'Selecione um arquivo';
    populateFileChoices(activeFile);
    updateTabularLinks(activeFile);
    loadPresets();
  }

  function populateFileChoices(reference) {
    const currentPath = reference?.path || fileSelect.value;
    const available = reference
      ? files.filter((file) => file.system === reference.system && file.kind === reference.kind && file.uf === reference.uf)
      : files;
    fileSelect.replaceChildren(new Option(available.length ? 'Escolha um arquivo DBC…' : 'Nenhuma base compatível', ''));
    available.forEach((file) => {
      const label = `${file.system} · ${file.kind} · ${period(file)} · ${file.name}${file.converted ? ' · leitura pronta' : ''}`;
      fileSelect.add(new Option(label, file.path));
    });
    if (available.some((file) => file.path === currentPath)) fileSelect.value = currentPath;
  }

  async function init() {
    try {
      const data = await request({ action: 'catalog' });
      files = Array.isArray(data.files) ? data.files : [];
      let previousPath = '';
      try { previousPath = localStorage.getItem(ACTIVE_FILE_KEY) || ''; } catch (_) {}
      populateFileChoices(null);
      if (previousPath && files.some((file) => file.path === previousPath)) {
        fileSelect.value = previousPath;
        chooseFile(previousPath, false);
      } else {
        try { localStorage.removeItem(ACTIVE_FILE_KEY); } catch (_) {}
        window.dispatchEvent(new Event('spptab-active-file-change'));
        setInfo(files.length ? 'Selecione um DBC da biblioteca para consultar as combinações compatíveis.' : 'Sua biblioteca ainda está vazia. Importe um arquivo DBC para começar.');
        renderEmpty(files.length ? 'Selecione uma base para começar' : 'Nenhuma base na biblioteca', files.length ? 'Depois de escolher o DBC, mostraremos as combinações que podem ser aplicadas a ele.' : 'Use “Buscar arquivos” para baixar ou importar uma base ambulatorial ou hospitalar.');
      }
    } catch (error) {
      fileSelect.replaceChildren(new Option('Não foi possível abrir a biblioteca', ''));
      setInfo(error.message, true);
      renderEmpty('Não foi possível consultar a biblioteca', 'Confira se o serviço local do SPPtab está ativo e tente novamente.');
    }
  }

  fileSelect.addEventListener('change', () => chooseFile(fileSelect.value));
  init();
})();
