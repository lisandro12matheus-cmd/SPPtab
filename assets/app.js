(() => {
  'use strict';
  const apiUrl = 'api.php';
  const system = document.querySelector('#system');
  const year = document.querySelector('#year');
  const month = document.querySelector('#month');
  const searchButton = document.querySelector('#searchButton');
  const downloadButton = document.querySelector('#downloadButton');
  const emptyTitle = document.querySelector('#emptyTitle');
  const emptyCopy = document.querySelector('#emptyCopy');
  const emptyState = document.querySelector('#emptyState');
  const resultsContent = document.querySelector('#resultsContent');
  const fileRows = document.querySelector('#fileRows');
  const notice = document.querySelector('#notice');
  const monthNames = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho','Agosto','Setembro','Outubro','Novembro','Dezembro'];
  let currentFiles = [];
  let busy = false;

  const currentYear = new Date().getFullYear();
  for (let y = currentYear; y >= 2008; y -= 1) {
    const option = document.createElement('option');
    option.value = String(y);
    option.textContent = String(y);
    year.append(option);
  }
  year.value = String(currentYear);

  async function request(payload) {
    const response = await fetch(apiUrl, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload), credentials: 'same-origin'
    });
    let data;
    try { data = await response.json(); }
    catch (_) { throw new Error(`O servidor respondeu sem JSON válido (HTTP ${response.status}). Confira o serviço PHP e tente novamente.`); }
    if (!response.ok || !data.ok) throw new Error(data.error || 'Não foi possível concluir a solicitação.');
    return data;
  }

  function setEmpty(title, copy) {
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

  async function loadCompetencies(preferredMonth = null) {
    clearNotice();
    currentFiles = [];
    downloadButton.disabled = true;
    searchButton.disabled = true;
    month.disabled = true;
    month.innerHTML = '<option value="">Buscando períodos…</option>';
    setEmpty('Consultando competências', 'Estamos verificando quais meses já foram publicados para esta base.');
    try {
      const data = await request({action:'competencies', system:system.value, year:Number(year.value)});
      month.innerHTML = '';
      if (!data.months.length) {
        month.add(new Option('Nenhuma competência', ''));
        setEmpty('Ainda sem arquivos neste ano', 'Escolha outro ano para consultar as competências disponíveis.');
        return;
      }
      data.months.forEach((m) => month.add(new Option(monthNames[m - 1], String(m).padStart(2, '0'))));
      month.disabled = false;
      const selected = data.months.includes(Number(preferredMonth)) ? Number(preferredMonth) : data.months[data.months.length - 1];
      month.value = String(selected).padStart(2, '0');
      await searchFiles();
    } catch (error) {
      month.innerHTML = '<option value="">Indisponível</option>';
      setEmpty('Não foi possível consultar o DATASUS', 'Confira sua conexão e tente buscar novamente.');
      showNotice(error.message, 'error');
    } finally {
      searchButton.disabled = false;
    }
  }

  function renderFiles(files) {
    currentFiles = files;
    fileRows.innerHTML = '';
    files.forEach((file, index) => {
      const row = document.createElement('tr');
      const updated = file.modified && /^\d{14}$/.test(file.modified)
        ? `${file.modified.slice(6,8)}/${file.modified.slice(4,6)}/${file.modified.slice(0,4)}` : '—';
      const isSaved = Boolean(file.downloaded);
      const status = isSaved ? '<span class="saved-pill">Na biblioteca</span>' : file.incomplete ? '<span class="incomplete-pill">Importação incompleta</span>' : '<span class="pending-pill">Disponível</span>';
      row.innerHTML = `<td><input class="file-check" type="checkbox" aria-label="Selecionar ${escapeHtml(file.name)}" data-index="${index}" ${isSaved ? 'disabled' : ''}></td>
        <td><div class="file-identity"><span class="file-icon">DBC</span><span><strong>${escapeHtml(file.name)}</strong><small>Pará · competência ${String(file.month).padStart(2,'0')}/${year.value}</small></span></div></td>
        <td><span class="type-pill"><b>${escapeHtml(file.kind)}</b> ${escapeHtml(file.label)}</span></td>
        <td>${escapeHtml(file.size_label || '—')}</td><td>${status}</td><td>${updated}</td>`;
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

  async function searchFiles() {
    if (!month.value) return;
    clearNotice();
    searchButton.disabled = true;
    setEmpty('Buscando arquivos', 'A lista da competência está sendo consultada no DATASUS.');
    try {
      const data = await request({action:'files', system:system.value, year:Number(year.value), month:Number(month.value)});
      if (!data.files.length) {
        currentFiles = [];
        setEmpty('Nenhum arquivo encontrado', 'Esta competência ainda não tem arquivos publicados para a base selecionada.');
        showNotice('Tente outra competência ou outro conjunto de dados.', 'info');
      } else renderFiles(data.files);
    } catch (error) {
      setEmpty('Não foi possível buscar os arquivos', 'Tente novamente em instantes.');
      showNotice(error.message, 'error');
    } finally {
      searchButton.disabled = false;
    }
  }

  async function downloadSelected() {
    const names = [...fileRows.querySelectorAll('.file-check:checked')].map((box) => currentFiles[Number(box.dataset.index)].name);
    if (!names.length || busy) return;
    busy = true;
    downloadButton.disabled = true;
    searchButton.disabled = true;
    downloadButton.innerHTML = '<span class="spinner"></span> Importando arquivos…';
    showNotice('A transferência está em andamento. Arquivos grandes podem levar alguns minutos.', 'info');
    try {
      const data = await request({action:'download', system:system.value, year:Number(year.value), month:Number(month.value), names});
      const count = data.files.length;
      const already = data.files.filter((file) => file.already_present).length;
      const suffix = already ? ` ${already} ${already === 1 ? 'já estava na biblioteca.' : 'já estavam na biblioteca.'}` : '';
      showNotice(`${count} ${count === 1 ? 'arquivo salvo' : 'arquivos salvos'} em uploads/${system.value.toUpperCase()}/${year.value}/${String(month.value).padStart(2,'0')}.${suffix}`, 'success');
      const saved = new Set(data.files.map((file) => file.name.toUpperCase()));
      currentFiles = currentFiles.map((file) => saved.has(file.name.toUpperCase()) ? {...file, downloaded:true, incomplete:false} : file);
      renderFiles(currentFiles);
    } catch (error) {
      showNotice(error.message, 'error');
    } finally {
      busy = false;
      downloadButton.innerHTML = 'Adicionar à biblioteca <span aria-hidden="true">→</span>';
      searchButton.disabled = false;
      updateSelection();
    }
  }

  system.addEventListener('change', () => loadCompetencies());
  year.addEventListener('change', () => loadCompetencies());
  month.addEventListener('change', searchFiles);
  searchButton.addEventListener('click', searchFiles);
  downloadButton.addEventListener('click', downloadSelected);
  document.querySelector('#selectAll').addEventListener('click', () => {
    const boxes = [...fileRows.querySelectorAll('.file-check:not(:disabled)')];
    const shouldCheck = boxes.some((box) => !box.checked);
    boxes.forEach((box) => { box.checked = shouldCheck; });
    updateSelection();
  });
  fileRows.addEventListener('change', updateSelection);

  const spinnerStyle = document.createElement('style');
  spinnerStyle.textContent = '.spinner{width:12px;height:12px;border:2px solid rgba(255,255,255,.4);border-top-color:#fff;border-radius:50%;animation:spin .75s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}';
  document.head.append(spinnerStyle);
  loadCompetencies();
})();
