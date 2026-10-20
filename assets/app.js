(() => {
  'use strict';
  const apiUrl = 'api.php';
  const system = document.querySelector('#system');
  const year = document.querySelector('#year');
  const month = document.querySelector('#month');
  const searchButton = document.querySelector('#searchButton');
  const ufSelect = document.querySelector('#uf');
  const municipalitySelect = document.querySelector('#municipality');
  const locationStep = document.querySelector('#locationStep');
  const filesStep = document.querySelector('#filesStep');
  const pageIntro = document.querySelector('#pageIntro');
  const advanceButton = document.querySelector('#advanceToFiles');
  const changeStateButton = document.querySelector('#changeStateButton');
  const downloadButton = document.querySelector('#downloadButton');
  const emptyTitle = document.querySelector('#emptyTitle');
  const emptyCopy = document.querySelector('#emptyCopy');
  const emptyState = document.querySelector('#emptyState');
  const emptyIcon = document.querySelector('#emptyIcon');
  const searchLoader = document.querySelector('#searchLoader');
  const queryProgress = document.querySelector('#queryProgress');
  const queryProgressTrack = document.querySelector('#queryProgressTrack');
  const queryProgressFill = document.querySelector('#queryProgressFill');
  const queryProgressStage = document.querySelector('#queryProgressStage');
  const queryProgressPercent = document.querySelector('#queryProgressPercent');
  const results = document.querySelector('#results');
  const resultsContent = document.querySelector('#resultsContent');
  const fileRows = document.querySelector('#fileRows');
  const notice = document.querySelector('#notice');
  const monthNames = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho','Agosto','Setembro','Outubro','Novembro','Dezembro'];
  const ACTIVE_FILE_KEY = 'spptab-active-file-v1';
  const stateNames = {AC:'Acre',AL:'Alagoas',AP:'Amapá',AM:'Amazonas',BA:'Bahia',CE:'Ceará',DF:'Distrito Federal',ES:'Espírito Santo',GO:'Goiás',MA:'Maranhão',MT:'Mato Grosso',MS:'Mato Grosso do Sul',MG:'Minas Gerais',PA:'Pará',PB:'Paraíba',PR:'Paraná',PE:'Pernambuco',PI:'Piauí',RJ:'Rio de Janeiro',RN:'Rio Grande do Norte',RS:'Rio Grande do Sul',RO:'Rondônia',RR:'Roraima',SC:'Santa Catarina',SP:'São Paulo',SE:'Sergipe',TO:'Tocantins'};
  const LOCATION_KEY = 'spptab-location-v1';
  let location = {uf:'', municipalityCode:'', municipalityName:''};
  let municipalityRequest = 0;
  let currentFiles = [];
  let busy = false;
  let loadingTimer = null;
  let progressFinishTimer = null;
  let progressStartedAt = 0;
  let progressWasShown = false;
  let activeLoadingStage = -1;
  let competencyContext = '';
  let competencyFilesByMonth = new Map();
  let competencySourceMode = '';
  let competencyCacheComplete = false;
  let pendingCompetencyContext = '';
  let pendingCompetencyPromise = null;
  let prefetchTimer = null;
  let competenciesRequest = 0;
  let filesRequest = 0;

  const currentYear = new Date().getFullYear();
  for (let y = currentYear; y >= 2008; y -= 1) {
    const option = document.createElement('option');
    option.value = String(y);
    option.textContent = String(y);
    year.append(option);
  }
  year.value = String(currentYear);
  month.innerHTML = '<option value="">Escolha uma localidade primeiro</option>';
  searchButton.disabled = true;

  async function request(payload) {
    const response = await fetch(apiUrl, {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-SPPtab-CSRF': document.querySelector('meta[name="csrf-token"]')?.content || ''},
      body: JSON.stringify(payload), credentials: 'same-origin'
    });
    let data;
    try { data = await response.json(); }
    catch (_) { throw new Error(`O servidor respondeu sem JSON válido (HTTP ${response.status}). Confira o serviço PHP e tente novamente.`); }
    if (!response.ok || !data.ok) throw new Error(data.error || 'Não foi possível concluir a solicitação.');
    return data;
  }

  function stopLoading(completed = false) {
    if (loadingTimer !== null) clearInterval(loadingTimer);
    loadingTimer = null;
    emptyState.classList.remove('is-loading');
    results.setAttribute('aria-busy', 'false');
    searchLoader.hidden = true;
    emptyIcon.hidden = false;
    if (progressFinishTimer !== null) clearTimeout(progressFinishTimer);
    progressFinishTimer = null;
    if (completed && progressWasShown) {
      queryProgress.hidden = false;
      queryProgressStage.textContent = 'Consulta concluída';
      queryProgressPercent.textContent = '100%';
      queryProgressFill.style.width = '100%';
      queryProgressTrack.setAttribute('aria-valuenow', '100');
      queryProgressTrack.setAttribute('aria-valuetext', 'Consulta concluída');
      queryProgressTrack.classList.add('is-complete');
      progressFinishTimer = setTimeout(() => {
        queryProgress.hidden = true;
        queryProgressFill.style.width = '0%';
        queryProgressTrack.setAttribute('aria-valuenow', '0');
        queryProgressTrack.setAttribute('aria-valuetext', 'Estimativa visual enquanto a fonte responde');
        queryProgressTrack.classList.remove('is-complete');
        progressStartedAt = 0;
        progressWasShown = false;
      }, 300);
    } else {
      queryProgress.hidden = true;
      queryProgressFill.style.width = '0%';
      queryProgressTrack.setAttribute('aria-valuenow', '0');
      queryProgressTrack.setAttribute('aria-valuetext', 'Estimativa visual enquanto a fonte responde');
      queryProgressTrack.classList.remove('is-complete');
      progressStartedAt = 0;
      progressWasShown = false;
    }
  }

  function startEstimatedProgress(messages, updateEmptyState) {
    progressStartedAt = Date.now();
    activeLoadingStage = -1;
    progressWasShown = false;
    const showProgress = () => {
      const elapsed = Date.now() - progressStartedAt;
      const stageIndex = Math.min(messages.length - 1, elapsed < 1400 ? 0 : elapsed < 5000 ? 1 : 2);
      const message = messages[stageIndex];
      if (updateEmptyState && stageIndex !== activeLoadingStage) {
        emptyTitle.textContent = message.title;
        emptyCopy.textContent = message.copy;
      }
      activeLoadingStage = stageIndex;
      queryProgressStage.textContent = message.title;
      if (elapsed >= 180) {
        queryProgress.hidden = false;
        progressWasShown = true;
      }
      const percent = Math.min(92, Math.round(94 * (1 - Math.exp(-elapsed / 4200))));
      queryProgressPercent.textContent = `~${percent}%`;
      queryProgressFill.style.width = `${percent}%`;
      queryProgressTrack.setAttribute('aria-valuenow', String(percent));
      queryProgressTrack.setAttribute('aria-valuetext', `Estimativa visual de ${percent}% enquanto a fonte responde`);
    };
    showProgress();
    loadingTimer = setInterval(showProgress, 120);
  }

  function setLoading(messages) {
    stopLoading();
    emptyState.hidden = false;
    resultsContent.hidden = true;
    emptyState.classList.add('is-loading');
    results.setAttribute('aria-busy', 'true');
    emptyIcon.hidden = true;
    searchLoader.hidden = false;
    startEstimatedProgress(messages, true);
  }

  function setBackgroundLoading(messages) {
    stopLoading();
    results.setAttribute('aria-busy', 'true');
    startEstimatedProgress(messages, false);
  }

  function setEmpty(title, copy) {
    stopLoading();
    emptyState.hidden = false;
    resultsContent.hidden = true;
    emptyTitle.textContent = title;
    emptyCopy.textContent = copy;
  }

  function showNotice(message, kind = 'info') {
    notice.className = `notice ${kind}`;
    notice.textContent = message;
    notice.hidden = false;
  }

  function clearNotice() { notice.hidden = true; notice.textContent = ''; }

  function stateLabel(uf = location.uf) {
    return uf ? `${stateNames[uf] || uf} · ${uf}` : 'estado selecionado';
  }

  function setSelectedMapState(uf) {
    document.querySelectorAll('#mapMount [data-uf]').forEach((path) => {
      const selected = path.dataset.uf === uf;
      path.classList.toggle('is-selected', selected);
      path.setAttribute('aria-pressed', selected ? 'true' : 'false');
    });
    const tooltip = document.querySelector('#mapTooltip');
    if (tooltip) tooltip.textContent = uf ? `${stateNames[uf]} · ${uf}` : 'Passe o cursor ou use o teclado';
    const heading = document.querySelector('#locationHeading');
    if (heading) heading.textContent = uf ? `${stateNames[uf]} selecionado` : 'Selecione um estado';
    const mapKey = document.querySelector('#mapKeyText');
    if (mapKey) mapKey.textContent = uf ? 'Estado selecionado' : 'Selecione uma UF';
  }

  function updateLocationSummary() {
    const tag = document.querySelector('#locationTag b');
    const scope = document.querySelector('#scopeCopy');
    const hint = document.querySelector('#locationHint');
    if (!location.uf || !location.municipalityName) {
      if (tag) tag.textContent = location.uf ? `${stateNames[location.uf]} · ${location.uf}` : 'Escolha a UF';
      if (scope) scope.textContent = 'A lista acompanha o estado escolhido. O município selecionado poderá ser aplicado à tabulação quando o relatório tiver um campo municipal compatível; isso não altera a abrangência do arquivo DBC.';
      return;
    }
    const wholeState = !location.municipalityCode;
    if (tag) tag.textContent = `${location.uf} · ${wholeState ? 'Todo o estado' : location.municipalityName}`;
    if (scope) scope.innerHTML = wholeState
      ? `Os arquivos listados são do estado de <strong>${escapeHtml(stateNames[location.uf])}</strong>. A tabulação considerará todos os municípios dessa UF.`
      : `Os arquivos listados são do estado de <strong>${escapeHtml(stateNames[location.uf])}</strong>. <strong>${escapeHtml(location.municipalityName)}</strong> poderá ser usado como filtro municipal quando o relatório oferecer campo compatível, usando o código IBGE <strong>${escapeHtml(location.municipalityCode)}</strong>.`;
    if (hint) hint.textContent = wholeState
      ? `Arquivos de ${stateNames[location.uf]}; a tabulação incluirá todo o estado.`
      : `${location.municipalityName} poderá ser usado como filtro quando o relatório oferecer campo municipal compatível. Os DBCs continuam sendo arquivos estaduais.`;
  }

  async function loadMap() {
    const mount = document.querySelector('#mapMount');
    try {
      const response = await fetch('assets/brazil-states.svg?v=1', {cache:'force-cache'});
      if (!response.ok) throw new Error('Mapa indisponível');
      mount.innerHTML = await response.text();
      mount.setAttribute('aria-busy', 'false');
      document.querySelectorAll('#mapMount [data-uf]').forEach((path) => {
        const activate = () => { if (busy) return; ufSelect.value = path.dataset.uf; ufSelect.dispatchEvent(new Event('change', {bubbles:true})); };
        path.addEventListener('click', activate);
        path.addEventListener('keydown', (event) => {
          if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); activate(); }
        });
        path.addEventListener('pointerenter', () => { document.querySelector('#mapTooltip').textContent = `${path.dataset.name} · ${path.dataset.uf}`; });
        path.addEventListener('pointerleave', () => setSelectedMapState(ufSelect.value));
        path.addEventListener('focus', () => { document.querySelector('#mapTooltip').textContent = `${path.dataset.name} · ${path.dataset.uf}`; });
        path.addEventListener('blur', () => setSelectedMapState(ufSelect.value));
      });
      setSelectedMapState(ufSelect.value);
    } catch (_) {
      mount.setAttribute('aria-busy', 'false');
      mount.innerHTML = '<div class="map-placeholder">Use a lista ao lado para escolher uma UF.</div>';
    }
  }

  async function loadMunicipalities(uf, preferred = '') {
    const requestId = ++municipalityRequest;
    municipalitySelect.disabled = true;
    municipalitySelect.innerHTML = '<option value="">Carregando municípios…</option>';
    document.querySelector('#municipalitySearch').disabled = true;
    document.querySelector('#municipalitySearch').value = '';
    document.querySelector('#locationHint').textContent = `Carregando a lista municipal opcional de ${stateNames[uf]}…`;
    try {
      const data = await request({action:'municipalities', uf});
      if (requestId !== municipalityRequest) return;
      municipalitySelect.innerHTML = '';
      municipalitySelect.add(new Option('Escolha um município…', ''));
      municipalitySelect.add(new Option('Todo o estado', 'all'));
      data.municipalities.forEach((item) => {
        const option = new Option(item.name, item.code);
        option.dataset.search = item.name.toLocaleLowerCase('pt-BR');
        municipalitySelect.add(option);
      });
      municipalitySelect.disabled = false;
      document.querySelector('#municipalitySearch').disabled = false;
      if (preferred && [...municipalitySelect.options].some((option) => option.value === preferred)) {
        municipalitySelect.value = preferred;
        handleMunicipalityChange();
      } else {
        municipalitySelect.value = 'all';
        handleMunicipalityChange();
        document.querySelector('#locationHint').textContent = `${data.municipalities.length.toLocaleString('pt-BR')} municípios disponíveis para o recorte opcional da tabulação.`;
      }
      if (data.source_mode === 'stale-cache') {
        document.querySelector('#locationHint').textContent += ' Exibindo a lista salva neste computador.';
      }
    } catch (error) {
      if (requestId !== municipalityRequest) return;
      municipalitySelect.innerHTML = '<option value="">Selecione o recorte municipal…</option>';
      municipalitySelect.add(new Option('Todo o estado', 'all'));
      municipalitySelect.value = 'all';
      municipalitySelect.disabled = false;
      document.querySelector('#municipalitySearch').disabled = true;
      handleMunicipalityChange();
      document.querySelector('#locationHint').textContent = 'A lista municipal não ficou disponível. Você pode continuar com todos os municípios do estado.';
    }
  }

  function handleUfChange() {
    competenciesRequest += 1;
    filesRequest += 1;
    const uf = ufSelect.value;
    setSelectedMapState(uf);
    advanceButton.disabled = !uf;
    location = {uf, municipalityCode:'', municipalityName:''};
    try { localStorage.removeItem(LOCATION_KEY); } catch (_) {}
    updateLocationSummary();
    clearNotice();
    currentFiles = [];
    downloadButton.disabled = true;
    searchButton.disabled = true;
    month.disabled = true;
    month.innerHTML = '<option value="">Escolha primeiro um estado</option>';
    if (!uf) {
      municipalityRequest += 1;
      municipalitySelect.disabled = true;
      municipalitySelect.innerHTML = '<option value="">Escolha primeiro um estado…</option>';
      document.querySelector('#municipalitySearch').disabled = true;
      document.querySelector('#locationHint').textContent = 'Escolha uma UF no mapa ou na lista para continuar.';
      return;
    }
    location.municipalityName = 'Todo o estado';
    try { localStorage.setItem(LOCATION_KEY, JSON.stringify(location)); } catch (_) {}
    updateLocationSummary();
    loadMunicipalities(uf, 'all');
    scheduleCompetencyPrefetch();
  }

  function handleMunicipalityChange() {
    if (!ufSelect.value) return;
    let value = municipalitySelect.value;
    if (!value) { value = 'all'; municipalitySelect.value = 'all'; }
    const option = municipalitySelect.selectedOptions[0];
    const municipalityName = value === 'all' ? 'Todo o estado' : option.textContent;
    location = {uf:ufSelect.value, municipalityCode:value === 'all' ? '' : value, municipalityName};
    try { localStorage.setItem(LOCATION_KEY, JSON.stringify(location)); } catch (_) {}
    updateLocationSummary();
  }

  async function restoreLocation() {
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem(LOCATION_KEY) || 'null'); } catch (_) {}
    if (!saved || !stateNames[saved.uf]) return;
    ufSelect.value = saved.uf;
    setSelectedMapState(saved.uf);
    advanceButton.disabled = false;
    location = {uf:saved.uf, municipalityCode:'', municipalityName:'Todo o estado'};
    updateLocationSummary();
    scheduleCompetencyPrefetch();
    await loadMunicipalities(saved.uf, saved.municipalityCode || 'all');
  }

  function showFilesStep() {
    if (!location.uf || !location.municipalityName || busy) return;
    locationStep.hidden = true;
    filesStep.hidden = false;
    pageIntro.hidden = true;
    document.querySelector('#progressLocation').classList.remove('active');
    document.querySelector('#progressLocation').classList.add('complete');
    document.querySelector('#progressLocation').removeAttribute('aria-current');
    document.querySelector('#progressFiles').classList.add('active');
    document.querySelector('#progressFiles').setAttribute('aria-current', 'step');
    document.querySelector('#pageStepLabel').textContent = 'etapa 1 de 3 · arquivos';
    loadCompetencies();
    filesStep.scrollIntoView({behavior:'smooth', block:'start'});
  }

  function showLocationStep() {
    if (busy) return;
    competenciesRequest += 1;
    filesRequest += 1;
    stopLoading();
    filesStep.hidden = true;
    locationStep.hidden = false;
    pageIntro.hidden = false;
    document.querySelector('#progressLocation').classList.remove('complete');
    document.querySelector('#progressLocation').classList.add('active');
    document.querySelector('#progressLocation').setAttribute('aria-current', 'step');
    document.querySelector('#progressFiles').classList.remove('active');
    document.querySelector('#progressFiles').removeAttribute('aria-current');
    document.querySelector('#pageStepLabel').textContent = 'etapa 1 de 3';
    locationStep.scrollIntoView({behavior:'smooth', block:'start'});
  }

  function filterMunicipalityOptions() {
    const term = document.querySelector('#municipalitySearch').value.trim().toLocaleLowerCase('pt-BR');
    Array.from(municipalitySelect.options).forEach((option) => {
      option.hidden = Boolean(term && option.value && option.value !== 'all' && !(option.dataset.search || option.textContent.toLocaleLowerCase('pt-BR')).includes(term));
    });
  }

  async function loadCompetencies(preferredMonth = null) {
    if (!location.uf || !location.municipalityName) return;
    const requestedSystem = system.value;
    const requestedYear = Number(year.value);
    const context = competencyKey(requestedSystem, requestedYear, location.uf);
    if (context === competencyContext && showCachedCompetencies(preferredMonth)) return;
    competencyContext = '';
    competencyFilesByMonth = new Map();
    competencySourceMode = '';
    competencyCacheComplete = false;
    const requestId = ++competenciesRequest;
    filesRequest += 1;
    const requestedUf = location.uf;
    clearNotice();
    currentFiles = [];
    downloadButton.disabled = true;
    searchButton.disabled = true;
    month.disabled = true;
    month.innerHTML = '<option value="">Buscando períodos…</option>';
    const base = requestedSystem === 'sia' ? 'ambulatorial' : 'hospitalar';
    setLoading([
      {title:'Indo ao DATASUS', copy:`Abrindo a consulta da base ${base} de ${stateLabel()} para ${year.value}.`},
      {title:'Consultando as competências', copy:'Verificando quais meses já foram publicados na fonte oficial.'},
      {title:'A consulta ainda está ativa', copy:'Aguarde mais um pouco. Assim que o DATASUS responder, mostraremos os períodos disponíveis.'}
    ]);
    try {
      const data = await fetchCompetencies(context, requestedSystem, requestedYear, requestedUf);
      if (requestId !== competenciesRequest || requestedUf !== location.uf) return;
      if (Array.isArray(data.files)) {
        cacheCompetencyRows(context, data.files, data.source_mode, data.months || [], true);
        showCachedCompetencies(preferredMonth);
      } else {
        month.innerHTML = '';
        if (!data.months.length) {
          month.add(new Option('Nenhuma competência', ''));
          setEmpty('Ainda sem arquivos neste ano', `Escolha outro ano para consultar as competências disponíveis em ${stateNames[location.uf]}.`);
          return;
        }
        data.months.forEach((m) => month.add(new Option(monthNames[m - 1], String(m).padStart(2, '0'))));
        month.disabled = false;
        const selected = data.months.includes(Number(preferredMonth)) ? Number(preferredMonth) : data.months[data.months.length - 1];
        month.value = String(selected).padStart(2, '0');
        await searchFiles();
      }
    } catch (error) {
      if (requestId !== competenciesRequest || requestedUf !== location.uf) return;
      month.innerHTML = '<option value="">Indisponível</option>';
      setEmpty('Não foi possível consultar o DATASUS', 'Confira sua conexão e tente buscar novamente.');
      showNotice(error.message, 'error');
    } finally {
      if (requestId === competenciesRequest) searchButton.disabled = !month.value;
    }
  }

  function renderFiles(files) {
    stopLoading(true);
    currentFiles = files;
    fileRows.innerHTML = '';
    files.forEach((file, index) => {
      const row = document.createElement('tr');
      row.className = 'file-data-row';
      const updated = file.modified && /^\d{14}$/.test(file.modified)
        ? `${file.modified.slice(6,8)}/${file.modified.slice(4,6)}/${file.modified.slice(0,4)}` : '—';
      const isSaved = Boolean(file.downloaded);
      const status = isSaved ? '<span class="saved-pill">Na biblioteca</span>' : file.incomplete ? '<span class="incomplete-pill">Importação incompleta</span>' : '<span class="pending-pill">Disponível</span>';
      row.innerHTML = `<td><input class="file-check" type="checkbox" aria-label="Selecionar ${escapeHtml(file.name)}" data-index="${index}"></td>
        <td><div class="file-identity"><span class="file-icon">DBC</span><span><strong>${escapeHtml(file.name)}</strong><small>${escapeHtml(stateNames[file.uf || location.uf] || file.uf || location.uf)} · competência ${String(file.month).padStart(2,'0')}/${year.value}</small></span></div></td>
        <td><span class="type-pill"><b>${escapeHtml(file.kind)}</b> ${escapeHtml(file.label)}</span></td>
        <td>${escapeHtml(file.size_label || '—')}</td><td>${status}</td><td>${updated}</td><td class="file-action-cell"></td>`;
      {
        const actionCell = row.querySelector('.file-action-cell');
        const openTabulation = document.createElement('button');
        openTabulation.type = 'button';
        openTabulation.className = 'file-action-link';
        openTabulation.textContent = 'Abrir tabulação';
        openTabulation.setAttribute('aria-label', isSaved ? `Abrir ${file.name} para tabular` : `Baixar e abrir ${file.name} para tabular`);
        if (!isSaved) openTabulation.title = 'O arquivo será baixado antes de abrir a tabulação.';
        openTabulation.addEventListener('click', () => {
          if (isSaved && file.local_path) {
            try { localStorage.setItem(ACTIVE_FILE_KEY, file.local_path); } catch (_) {}
            window.location.href = `tabular.php?stage=3&file=${encodeURIComponent(file.local_path)}`;
            return;
          }
          downloadSelected(file, openTabulation);
        });
        actionCell.append(openTabulation);
      }
      fileRows.append(row);
    });
    document.querySelector('#fileCount').textContent = String(files.length);
    document.querySelector('#resultsSummary').textContent = `${files.length} ${files.length === 1 ? 'arquivo disponível' : 'arquivos disponíveis'} para ${monthNames[Number(month.value) - 1]} de ${year.value}.`;
    emptyState.hidden = true;
    resultsContent.hidden = false;
    updateSelection();
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  }

  function updateSelection() {
    const checked = [...fileRows.querySelectorAll('.file-check:checked')];
    fileRows.querySelectorAll('.file-check').forEach((box) => {
      box.closest('tr')?.classList.toggle('is-selected', box.checked);
    });
    const totalSize = checked.reduce((sum, box) => sum + (Number(currentFiles[Number(box.dataset.index)]?.size) || 0), 0);
    document.querySelector('#selectedCount').textContent = `${checked.length} ${checked.length === 1 ? 'arquivo selecionado' : 'arquivos selecionados'}`;
    document.querySelector('#selectedSize').textContent = checked.length ? `Total aproximado · ${formatBytes(totalSize)}` : 'Escolha um ou mais arquivos para continuar';
    downloadButton.disabled = checked.length === 0 || busy;
    const selectable = fileRows.querySelectorAll('.file-check:not(:disabled)').length;
    document.querySelector('#selectAll').textContent = checked.length === selectable && selectable ? 'Limpar seleção' : 'Selecionar todos';
  }

  function formatBytes(bytes) {
    if (!bytes) return 'tamanho não informado';
    const units = ['B','KB','MB','GB'];
    let value = bytes, i = 0;
    while (value >= 1024 && i < units.length - 1) { value /= 1024; i += 1; }
    return `${value.toLocaleString('pt-BR', {maximumFractionDigits:1})} ${units[i]}`;
  }

  function showFileResults(data) {
    if (!data.files.length) {
      currentFiles = [];
      setEmpty('Nenhum arquivo encontrado', 'Esta competência ainda não tem arquivos publicados para a base selecionada.');
      showNotice('Tente outra competência ou outro conjunto de dados.', 'info');
    } else {
      renderFiles(data.files);
      if (data.source_mode === 'local') {
        showNotice('O DATASUS está inacessível nesta rede. Mostrando os arquivos já salvos na biblioteca deste computador.', 'info');
      } else if (data.source_mode === 'stale-cache') {
        showNotice('O DATASUS não respondeu agora. Mostrando a última lista de arquivos salva neste computador.', 'info');
      }
    }
  }

  function competencyKey(systemCode = system.value, dataYear = year.value, uf = location.uf) {
    return `${systemCode}:${dataYear}:${uf}`;
  }

  function cacheCompetencyRows(context, files, sourceMode, months = [], complete = true) {
    const byMonth = new Map();
    months.forEach((value) => byMonth.set(Number(value), {files:[], sourceMode}));
    files.forEach((file) => {
      const key = Number(file.month);
      if (!byMonth.has(key)) byMonth.set(key, {files:[], sourceMode});
      byMonth.get(key).files.push(file);
    });
    competencyContext = context;
    competencyFilesByMonth = byMonth;
    competencySourceMode = sourceMode || '';
    competencyCacheComplete = complete;
  }

  function fetchCompetencies(context, systemCode, dataYear, uf) {
    if (pendingCompetencyContext === context && pendingCompetencyPromise) return pendingCompetencyPromise;
    const promise = request({action:'competencies', system:systemCode, year:dataYear, uf});
    pendingCompetencyContext = context;
    pendingCompetencyPromise = promise;
    const clearPending = () => {
      if (pendingCompetencyPromise === promise) {
        pendingCompetencyContext = '';
        pendingCompetencyPromise = null;
      }
    };
    promise.then(clearPending, clearPending);
    return promise;
  }

  function prefetchCompetencies(uf = location.uf) {
    if (!uf) return;
    const systemCode = system.value;
    const dataYear = Number(year.value);
    const context = competencyKey(systemCode, dataYear, uf);
    if (competencyCacheComplete && competencyContext === context) return;
    fetchCompetencies(context, systemCode, dataYear, uf).then((data) => {
      if (competencyKey() !== context || !Array.isArray(data.files)) return;
      cacheCompetencyRows(context, data.files, data.source_mode, data.months || [], true);
    }).catch(() => {});
  }

  function scheduleCompetencyPrefetch() {
    if (prefetchTimer !== null) clearTimeout(prefetchTimer);
    const uf = location.uf;
    prefetchTimer = setTimeout(() => {
      prefetchTimer = null;
      if (uf === location.uf) prefetchCompetencies(uf);
    }, 250);
  }

  function showCachedCompetencies(preferredMonth = null) {
    if (!competencyCacheComplete || competencyContext !== competencyKey()) return false;
    const months = [...competencyFilesByMonth.keys()].sort((a, b) => a - b);
    month.innerHTML = '';
    if (!months.length) {
      month.add(new Option('Nenhuma competência', ''));
      month.disabled = true;
      searchButton.disabled = true;
      setEmpty('Ainda sem arquivos neste ano', `Escolha outro ano para consultar as competências disponíveis em ${stateNames[location.uf]}.`);
      return true;
    }
    months.forEach((value) => month.add(new Option(monthNames[value - 1], String(value).padStart(2, '0'))));
    month.disabled = false;
    const preferred = Number(preferredMonth || month.value);
    const selected = months.includes(preferred) ? preferred : months[months.length - 1];
    month.value = String(selected).padStart(2, '0');
    searchButton.disabled = false;
    clearNotice();
    showFileResults({files:competencyFilesByMonth.get(selected)?.files || [], source_mode:competencySourceMode});
    return true;
  }

  function showCachedMonth() {
    const selectedMonth = Number(month.value);
    if (!selectedMonth || competencyContext !== competencyKey() || !competencyFilesByMonth.has(selectedMonth)) return false;
    clearNotice();
    const cached = competencyFilesByMonth.get(selectedMonth);
    showFileResults({files:cached.files, source_mode:cached.sourceMode || competencySourceMode});
    return true;
  }

  async function searchFiles() {
    if (!month.value) return;
    const requestId = ++filesRequest;
    const requestedUf = location.uf;
    const requestedMonth = month.value;
    const requestedSystem = system.value;
    const requestedYear = Number(year.value);
    clearNotice();
    searchButton.disabled = true;
    const period = `${monthNames[Number(requestedMonth) - 1]} de ${requestedYear}`;
    setLoading([
      {title:'Consultando o DATASUS', copy:`Localizando os arquivos de ${period} para ${stateLabel()}.`},
      {title:'Conferindo os arquivos', copy:'Verificando o que está disponível e o que já foi salvo neste computador.'},
      {title:'A consulta ainda está ativa', copy:'Aguarde mais um pouco. A lista aparecerá assim que o DATASUS responder.'}
    ]);
    try {
      const data = await request({action:'files', system:requestedSystem, year:requestedYear, month:Number(requestedMonth), uf:requestedUf});
      if (requestId !== filesRequest || requestedUf !== location.uf) return;
      const context = competencyKey(requestedSystem, requestedYear, requestedUf);
      if (competencyContext !== context) cacheCompetencyRows(context, data.files || [], data.source_mode, [Number(requestedMonth)], false);
      else {
        competencyFilesByMonth.set(Number(requestedMonth), {files:data.files || [], sourceMode:data.source_mode || ''});
        competencySourceMode = data.source_mode || competencySourceMode;
      }
      showFileResults(data);
    } catch (error) {
      if (requestId !== filesRequest || requestedUf !== location.uf) return;
      setEmpty('Não foi possível buscar os arquivos', 'Tente novamente em instantes.');
      showNotice(error.message, 'error');
    } finally {
      if (requestId === filesRequest) searchButton.disabled = !month.value;
    }
  }

  async function downloadSelected(openFile = null, openButton = null) {
    if (busy) return;
    const names = openFile
      ? [openFile.name]
      : [...fileRows.querySelectorAll('.file-check:checked')].map((box) => currentFiles[Number(box.dataset.index)]?.name);
    const validNames = names.filter((name) => typeof name === 'string' && name.trim()).map((name) => name.trim());
    if (!validNames.length) {
      showNotice('Não foi possível identificar o arquivo selecionado. Atualize a lista e selecione novamente.', 'error');
      return;
    }
    busy = true;
    changeStateButton.disabled = true;
    ufSelect.disabled = true;
    municipalitySelect.disabled = true;
    document.querySelector('#municipalitySearch').disabled = true;
    downloadButton.disabled = true;
    if (openButton) {
      openButton.disabled = true;
      openButton.textContent = 'Baixando…';
    }
    searchButton.disabled = true;
    downloadButton.innerHTML = '<span class="spinner"></span> Importando arquivos…';
    showNotice(openFile
      ? `Baixando ${openFile.name} para abrir a tabulação. Arquivos grandes podem levar alguns minutos.`
      : 'A transferência está em andamento. Arquivos grandes podem levar alguns minutos.', 'info');
    setBackgroundLoading([
      {title:'Solicitando os arquivos ao DATASUS', copy:'Conectando à fonte oficial.'},
      {title:'Recebendo os arquivos', copy:'O tempo depende do tamanho dos arquivos e da conexão.'},
      {title:'Validando e salvando na biblioteca', copy:'Aguarde a confirmação antes de fechar esta tela.'}
    ]);
    try {
      const data = await request({action:'download', system:system.value, year:Number(year.value), month:Number(month.value), uf:location.uf, names:validNames});
      const count = data.files.length;
      const already = data.files.filter((file) => file.already_present).length;
      const suffix = already ? ` ${already} ${already === 1 ? 'já estava na biblioteca.' : 'já estavam na biblioteca.'}` : '';
      const sources = [...new Set(data.files.map((file) => file.source_mode).filter((mode) => mode && mode !== 'biblioteca local'))];
      const sourceNote = sources.length ? ` Fonte: ${sources.join(' + ')}.` : '';
      showNotice(`${count} ${count === 1 ? 'arquivo salvo' : 'arquivos salvos'} em uploads/${system.value.toUpperCase()}/${year.value}/${String(month.value).padStart(2,'0')}.${suffix}${sourceNote}`, 'success');
      const saved = new Map(data.files.map((file) => [file.name.toUpperCase(), file]));
      const markImported = (file) => {
        const imported = saved.get(file.name.toUpperCase());
        return imported ? {...file, downloaded:true, incomplete:false, local_path:imported.path || file.local_path, size:imported.size || file.size} : file;
      };
      currentFiles = currentFiles.map(markImported);
      competencyFilesByMonth.forEach((cached) => { cached.files = cached.files.map(markImported); });
      renderFiles(currentFiles);
      if (openFile) {
        const imported = saved.get(openFile.name.toUpperCase());
        const path = imported?.path || openFile.local_path;
        if (!path) throw new Error('O arquivo foi salvo, mas não foi possível localizar seu caminho na biblioteca.');
        try { localStorage.setItem(ACTIVE_FILE_KEY, path); } catch (_) {}
        window.location.href = `tabular.php?stage=3&file=${encodeURIComponent(path)}`;
      }
    } catch (error) {
      stopLoading();
      showNotice(error.message, 'error');
    } finally {
      busy = false;
      changeStateButton.disabled = false;
      ufSelect.disabled = false;
      municipalitySelect.disabled = !ufSelect.value;
      document.querySelector('#municipalitySearch').disabled = !ufSelect.value;
      downloadButton.innerHTML = 'Adicionar à biblioteca <span aria-hidden="true">→</span>';
      searchButton.disabled = false;
      if (openButton?.isConnected) {
        openButton.disabled = false;
        openButton.textContent = 'Abrir tabulação';
      }
      updateSelection();
    }
  }

  ufSelect.addEventListener('change', handleUfChange);
  advanceButton.addEventListener('click', showFilesStep);
  changeStateButton.addEventListener('click', showLocationStep);
  municipalitySelect.addEventListener('change', handleMunicipalityChange);
  document.querySelector('#municipalitySearch').addEventListener('input', filterMunicipalityOptions);
  system.addEventListener('change', () => loadCompetencies());
  year.addEventListener('change', () => loadCompetencies());
  month.addEventListener('change', () => { if (!showCachedMonth()) searchFiles(); });
  searchButton.addEventListener('click', searchFiles);
  downloadButton.addEventListener('click', () => downloadSelected());
  document.querySelector('#selectAll').addEventListener('click', () => {
    const boxes = [...fileRows.querySelectorAll('.file-check:not(:disabled)')];
    const shouldCheck = boxes.some((box) => !box.checked);
    boxes.forEach((box) => { box.checked = shouldCheck; });
    updateSelection();
  });
  fileRows.addEventListener('change', updateSelection);
  fileRows.addEventListener('click', (event) => {
    if (!(event.target instanceof Element)) return;
    const row = event.target.closest('tr.file-data-row');
    if (!row || !fileRows.contains(row) || event.target.closest('button, a, input, select, textarea, label')) return;
    const checkbox = row.querySelector('.file-check:not(:disabled)');
    if (!checkbox) return;
    checkbox.checked = !checkbox.checked;
    checkbox.dispatchEvent(new Event('change', {bubbles:true}));
  });

  const spinnerStyle = document.createElement('style');
  spinnerStyle.textContent = '.spinner{width:12px;height:12px;border:2px solid rgba(255,255,255,.4);border-top-color:#fff;border-radius:50%;animation:spin .75s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}';
  document.head.append(spinnerStyle);
  loadMap();
  restoreLocation();
})();
