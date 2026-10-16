(() => {
  'use strict';

  const $ = (selector) => document.querySelector(selector);
  const stateNames = {AC:'Acre',AL:'Alagoas',AP:'Amapá',AM:'Amazonas',BA:'Bahia',CE:'Ceará',DF:'Distrito Federal',ES:'Espírito Santo',GO:'Goiás',MA:'Maranhão',MT:'Mato Grosso',MS:'Mato Grosso do Sul',MG:'Minas Gerais',PA:'Pará',PB:'Paraíba',PR:'Paraná',PE:'Pernambuco',PI:'Piauí',RJ:'Rio de Janeiro',RN:'Rio Grande do Norte',RS:'Rio Grande do Sul',RO:'Rondônia',RR:'Roraima',SC:'Santa Catarina',SP:'São Paulo',SE:'Sergipe',TO:'Tocantins'};
  const monthNames = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho','Agosto','Setembro','Outubro','Novembro','Dezembro'];
  const modulesOrder = ['ST','DC','PF','LT','EQ','EP','SR','HB','SIGTAP'];
  const $uf = $('#packageUf');
  const $year = $('#packageYear');
  const $month = $('#packageMonth');
  let competencies = [];
  let availableFiles = [];
  let selectedModules = new Set();
  let busy = false;
  let pollTimer = 0;

  function localLocation() {
    try { return JSON.parse(localStorage.getItem('spptab-location-v1') || 'null'); } catch (_) { return null; }
  }

  function formatSize(bytes) {
    const value = Number(bytes) || 0;
    if (!value) return 'Tamanho não informado';
    const units = ['B','KB','MB','GB'];
    let amount = value;
    let index = 0;
    while (amount >= 1024 && index < units.length - 1) { amount /= 1024; index += 1; }
    return `${amount.toLocaleString('pt-BR', { maximumFractionDigits: 1 })} ${units[index]}`;
  }

  async function request(payload) {
    const response = await fetch('api.php', { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin', body: JSON.stringify(payload) });
    const raw = await response.text();
    let data;
    try { data = JSON.parse(raw); } catch (_) { throw new Error(`O serviço de dados não respondeu corretamente (HTTP ${response.status}).`); }
    if (!response.ok || !data.ok) throw new Error(data.error || `Não foi possível concluir a operação (HTTP ${response.status}).`);
    return data;
  }

  function setNotice(message = '', error = false) {
    const notice = $('#packageNotice');
    notice.hidden = !message;
    notice.classList.toggle('error', Boolean(error));
    notice.textContent = message;
  }

  function setBusy(value) {
    busy = Boolean(value);
    $('#refreshCatalog').disabled = busy;
    $uf.disabled = busy;
    $year.disabled = busy || !competencies.length;
    $month.disabled = busy || !competencies.length;
    updateDownloadButton();
  }

  function chosenDateCompetencies() {
    const year = Number($year.value);
    return competencies.filter((item) => item.year === year).sort((a, b) => b.month - a.month);
  }

  function updateMonthOptions(preferredMonth = null) {
    const items = chosenDateCompetencies();
    $month.replaceChildren();
    items.forEach((item) => $month.add(new Option(monthNames[item.month - 1], String(item.month))));
    const selected = items.find((item) => item.month === Number(preferredMonth)) || items[0];
    if (selected) $month.value = String(selected.month);
  }

  function updateSelectionInfo() {
    const chosen = availableFiles.filter((item) => selectedModules.has(item.module));
    const total = chosen.reduce((sum, item) => sum + (Number(item.size) || 0), 0);
    $('#packageSelectionInfo').textContent = chosen.length
      ? `${chosen.length} módulo(s) selecionado(s) · ${formatSize(total)} no total. A conversão acontece depois do download.`
      : 'Selecione os módulos que deseja manter no computador.';
    updateDownloadButton();
  }

  function updateDownloadButton() {
    $('#downloadPackages').disabled = busy || !selectedModules.size || !availableFiles.some((item) => selectedModules.has(item.module) && !item.saved);
  }

  function renderCards(data) {
    const box = $('#packageCards');
    box.replaceChildren();
    const catalogFiles = [...(data.files || []), ...(data.sigtapPackage ? [data.sigtapPackage] : [])];
    const files = new Map(catalogFiles.map((item) => [item.module, item]));
    availableFiles = catalogFiles;
    selectedModules.clear();
    for (const module of modulesOrder) {
      const spec = data.modules?.[module];
      if (!spec) continue;
      const file = files.get(module);
      const card = document.createElement('label');
      card.className = `package-card${file?.saved ? ' is-saved' : ''}`;
      const icon = document.createElement('span');
      icon.className = 'package-card__icon';
      icon.textContent = module;
      const body = document.createElement('span');
      body.className = 'package-card__body';
      const title = document.createElement('strong');
      title.textContent = spec.label;
      const copy = document.createElement('p');
      copy.textContent = spec.description;
      const meta = document.createElement('span');
      meta.className = 'package-card__meta';
      const relation = document.createElement('span');
      relation.textContent = `Relaciona por ${spec.relationship}`;
      meta.append(relation);
      if (file) {
        const size = document.createElement('span');
        size.textContent = file.size_label || formatSize(file.size);
        meta.append(size);
        const status = document.createElement('span');
        status.textContent = file.saved ? 'Na biblioteca' : 'Disponível';
        status.className = file.saved ? 'saved' : '';
        meta.append(status);
      } else {
        const status = document.createElement('span');
        status.textContent = 'Não publicado nesta competência';
        status.className = 'missing';
        meta.append(status);
      }
      body.append(title, copy, meta);
      card.append(icon, body);
      const checkbox = document.createElement('input');
      checkbox.className = 'package-card__check';
      checkbox.type = 'checkbox';
      checkbox.setAttribute('aria-label', `Selecionar pacote de ${spec.label}`);
      checkbox.disabled = !file || file.saved || busy;
      if (file && !file.saved) {
        checkbox.addEventListener('change', () => {
          checkbox.checked ? selectedModules.add(module) : selectedModules.delete(module);
          updateSelectionInfo();
        });
      }
      card.append(checkbox);
      box.append(card);
    }
    const uf = stateNames[data.uf] || data.uf;
    const date = data.year && data.month ? `${monthNames[data.month - 1]} de ${data.year}` : 'a competência selecionada';
      const count = availableFiles.length;
    const sourceNote = data.sourceErrors?.length ? ` Algumas fontes não responderam: ${data.sourceErrors.join(' · ')}.` : '';
    $('#catalogStatus').textContent = count
      ? `${count} pacote(s) publicado(s) para ${uf} · ${date}. Selecione os que deseja baixar.${sourceNote}`
      : `Nenhum pacote CNES ou SIGTAP encontrado para ${uf} nessa competência.${sourceNote}`;
    if (!count) {
      const empty = document.createElement('div');
      empty.className = 'package-empty';
      empty.textContent = 'Escolha outra competência para ver os pacotes disponíveis.';
      box.append(empty);
    }
    updateSelectionInfo();
  }

  function renderCompetencies(data) {
    competencies = data.competencies || [];
    const years = [...new Set(competencies.map((item) => item.year))].sort((a, b) => b - a);
    $year.replaceChildren(...years.map((year) => new Option(String(year), String(year))));
    const selectedYear = years.includes(Number(data.year)) ? data.year : years[0];
    if (selectedYear) $year.value = String(selectedYear);
    updateMonthOptions(data.month);
  }

  async function loadCatalog(options = {}) {
    if (busy) return;
    setBusy(true);
    setNotice();
    $('#catalogStatus').textContent = 'Consultando as listas oficiais do CNES e do SIGTAP…';
    $('#packageCards').replaceChildren();
    try {
      const payload = { action: 'package_catalog', uf: $uf.value, refresh: Boolean(options.refresh) };
      if (options.selected) { payload.year = Number($year.value); payload.month = Number($month.value); }
      const data = await request(payload);
      if (!competencies.length || options.refresh) renderCompetencies(data);
      if (!options.selected && data.year && data.month) {
        if ([...$year.options].some((option) => Number(option.value) === Number(data.year))) $year.value = String(data.year);
        updateMonthOptions(data.month);
      }
      const exact = options.selected
        ? data
        : await request({ action: 'package_catalog', uf: $uf.value, year: Number($year.value), month: Number($month.value) });
      renderCards(exact);
      await loadLibrary();
    } catch (error) {
      $('#catalogStatus').textContent = error.message || 'Não foi possível consultar as fontes oficiais.';
      setNotice(error.message || 'Confira sua conexão e tente atualizar a lista.', true);
      $('#packageCards').replaceChildren();
    } finally {
      setBusy(false);
    }
  }

  function renderLibrary(items) {
    const box = $('#packageLocalGrid');
    box.replaceChildren();
    $('#packageLibraryCount').textContent = `${items.length} ${items.length === 1 ? 'pacote' : 'pacotes'}`;
    if (!items.length) {
      const empty = document.createElement('div');
      empty.className = 'package-library-empty';
      const title = document.createElement('strong');
      title.textContent = 'Ainda não há pacotes de dados neste estado';
      const copy = document.createElement('span');
      copy.textContent = 'Escolha módulos acima e baixe a competência que deseja cruzar.';
      empty.append(title, copy);
      box.append(empty);
      return;
    }
    items.forEach((item) => {
      const card = document.createElement('article');
      card.className = 'package-local-card';
      const head = document.createElement('div');
      head.className = 'package-local-card__head';
      const title = document.createElement('div');
      title.className = 'package-local-card__title';
      const badge = document.createElement('span');
      badge.textContent = item.module;
      const text = document.createElement('span');
      const strong = document.createElement('strong');
        strong.textContent = `${item.label} · ${item.uf === 'BR' ? 'Brasil' : item.uf}`;
      const sub = document.createElement('small');
      sub.textContent = `${monthNames[item.month - 1]} de ${item.year}`;
      text.append(strong, sub);
      title.append(badge, text);
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.textContent = 'Remover';
      remove.setAttribute('aria-label', `Remover pacote ${item.name}`);
      remove.addEventListener('click', async () => {
        remove.disabled = true;
        try {
          await request({ action: 'package_delete', path: item.path });
          setNotice(`${item.name} foi removido da biblioteca local.`);
          await loadLibrary();
          await refreshCurrentCards();
        } catch (error) {
          remove.disabled = false;
          setNotice(error.message, true);
        }
      });
      head.append(title, remove);
      const meta = document.createElement('div');
      meta.className = 'package-local-card__meta';
      [formatSize(item.size), `${Number(item.records).toLocaleString('pt-BR')} registros`, `${item.fields_count} campos`].forEach((value) => {
        const chip = document.createElement('span'); chip.textContent = value; meta.append(chip);
      });
      card.append(head, meta);
      box.append(card);
    });
  }

  async function loadLibrary() {
    const data = await request({ action: 'package_list', uf: $uf.value });
    renderLibrary(data.packages || []);
  }

  async function refreshCurrentCards() {
    const data = await request({ action: 'package_catalog', uf: $uf.value, year: Number($year.value), month: Number($month.value) });
    renderCards(data);
  }

  function setProgress(state) {
    const box = $('#packageProgress');
    box.hidden = false;
    const progress = Math.max(1, Math.min(100, Number(state.progress) || 0));
    $('#packageProgressStage').textContent = state.stage || 'Preparando pacotes';
    $('#packageProgressPercent').textContent = `${progress}%`;
    $('#packageProgressFill').style.width = `${progress}%`;
    box.querySelector('.progress-track').setAttribute('aria-valuenow', String(progress));
    const extra = state.bytes_written ? ` · ${formatSize(state.bytes_written)} processados` : '';
    $('#packageProgressCopy').textContent = `${state.message || 'Preparando os pacotes selecionados.'}${extra}`;
  }

  async function pollJob(jobId) {
    clearTimeout(pollTimer);
    try {
      const state = await request({ action: 'package_status', job_id: jobId });
      setProgress(state);
      if (state.status === 'done') {
        setBusy(false);
        setNotice(state.message || 'Pacotes preparados para cruzamento.');
        await refreshCurrentCards();
        await loadLibrary();
        return;
      }
      if (state.status === 'error') {
        setBusy(false);
        setNotice(state.message || 'Não foi possível preparar os pacotes.', true);
        return;
      }
      pollTimer = window.setTimeout(() => pollJob(jobId), 1000);
    } catch (error) {
      setBusy(false);
      setNotice(error.message, true);
    }
  }

  async function downloadSelected() {
    if (busy || !selectedModules.size) return;
    setBusy(true);
    $('#packageProgress').hidden = false;
    $('#packageProgressStage').textContent = 'Colocando os pacotes na fila';
    $('#packageProgressPercent').textContent = '1%';
    $('#packageProgressFill').style.width = '1%';
    $('#packageProgressCopy').textContent = 'A transferência começa em instantes.';
    setNotice();
    try {
      const data = await request({ action: 'package_download_start', uf: $uf.value, year: Number($year.value), month: Number($month.value), modules: [...selectedModules] });
      if (data.done) {
        setBusy(false);
        setProgress({ progress: 100, stage: 'Pacotes prontos', message: data.message });
        setNotice(data.message);
        await refreshCurrentCards();
        await loadLibrary();
      } else {
        pollJob(data.job_id);
      }
    } catch (error) {
      setBusy(false);
      setNotice(error.message, true);
      $('#packageProgress').hidden = true;
    }
  }

  function initStates() {
    Object.entries(stateNames).forEach(([code, name]) => $uf.add(new Option(`${name} · ${code}`, code)));
    const location = localLocation();
    if (location?.uf && stateNames[location.uf]) $uf.value = location.uf;
    $('#packageLocationTag').querySelector('b').textContent = stateNames[$uf.value] ? `${stateNames[$uf.value]} · ${$uf.value}` : 'Escolha a UF';
    $uf.addEventListener('change', () => {
      competencies = [];
      $year.replaceChildren(new Option('Carregando…', ''));
      $month.replaceChildren(new Option('Carregando…', ''));
      $('#packageLocationTag').querySelector('b').textContent = `${stateNames[$uf.value]} · ${$uf.value}`;
      loadCatalog({ refresh: true });
    });
    $year.addEventListener('change', () => { updateMonthOptions(); loadCatalog({ selected: true }); });
    $month.addEventListener('change', () => loadCatalog({ selected: true }));
    $('#refreshCatalog').addEventListener('click', () => loadCatalog({ refresh: true }));
    $('#downloadPackages').addEventListener('click', downloadSelected);
  }

  initStates();
  loadCatalog();
})();
