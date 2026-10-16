(() => {
  'use strict';

  const $ = (selector) => document.querySelector(selector);
  const rows = $('#libraryRows');
  const loading = $('#libraryLoading');
  const empty = $('#libraryEmpty');
  const notice = $('#libraryNotice');
  const search = $('#librarySearch');
  const systemFilter = $('#systemFilter');
  const dialog = $('#removeDialog');
  const confirmRemove = $('#confirmRemove');
  const cancelRemove = $('#cancelRemove');
  const monthNames = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho','Agosto','Setembro','Outubro','Novembro','Dezembro'];
  const stateNames = {AC:'Acre',AL:'Alagoas',AP:'Amapá',AM:'Amazonas',BA:'Bahia',CE:'Ceará',DF:'Distrito Federal',ES:'Espírito Santo',GO:'Goiás',MA:'Maranhão',MT:'Mato Grosso',MS:'Mato Grosso do Sul',MG:'Minas Gerais',PA:'Pará',PB:'Paraíba',PR:'Paraná',PE:'Pernambuco',PI:'Piauí',RJ:'Rio de Janeiro',RN:'Rio Grande do Norte',RS:'Rio Grande do Sul',RO:'Rondônia',RR:'Roraima',SC:'Santa Catarina',SE:'Sergipe',SP:'São Paulo',TO:'Tocantins'};
  let files = [];
  let pendingFile = null;
  let busy = false;

  async function request(payload) {
    const response = await fetch('api.php', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      credentials: 'same-origin',
      body: JSON.stringify(payload),
    });
    const raw = await response.text();
    let data;
    try { data = JSON.parse(raw); }
    catch (_) { throw new Error(`O servidor não devolveu uma resposta válida (HTTP ${response.status}).`); }
    if (!response.ok || !data.ok) throw new Error(data.error || `Não foi possível concluir a operação (HTTP ${response.status}).`);
    return data;
  }

  function formatBytes(value) {
    let number = Number(value) || 0;
    const units = ['B','KB','MB','GB'];
    let unit = 0;
    while (number >= 1024 && unit < units.length - 1) { number /= 1024; unit += 1; }
    return `${number.toLocaleString('pt-BR', {maximumFractionDigits: 1})} ${units[unit]}`;
  }

  function setNotice(message, type = 'info') {
    notice.textContent = message;
    notice.className = `bases-notice ${type}`;
    notice.hidden = false;
  }

  function clearNotice() { notice.hidden = true; notice.textContent = ''; }

  function statusOf(file) {
    if (file.converted) return {label:'DBF pronto', kind:'ready', detail:'Pronto para tabular'};
    if (file.conversion?.status === 'running' || file.conversion?.status === 'queued') return {label:'Convertendo', kind:'working', detail:'Conversão em andamento'};
    return {label:'DBC importado', kind:'pending', detail:'Aguardando conversão'};
  }

  function makeCell(className = '') {
    const td = document.createElement('td');
    if (className) td.className = className;
    return td;
  }

  function createRow(file) {
    const row = document.createElement('tr');
    const identity = makeCell('bases-file-cell');
    const identityWrap = document.createElement('div');
    identityWrap.className = 'bases-file-identity';
    const icon = document.createElement('span');
    icon.className = 'bases-file-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = 'DBC';
    const copy = document.createElement('span');
    copy.className = 'bases-file-copy';
    const filename = document.createElement('strong');
    filename.textContent = file.name;
    const period = document.createElement('small');
    const month = monthNames[(Number(file.month) || 1) - 1] || '';
    period.textContent = `${month} ${file.year} · ${String(file.kind || '').toUpperCase()}`;
    copy.append(filename, period);
    identityWrap.append(icon, copy);
    identity.append(identityWrap);

    const systemCell = makeCell();
    const systemPill = document.createElement('span');
    systemPill.className = `bases-system-pill ${file.system === 'SIH' ? 'is-sih' : 'is-sia'}`;
    systemPill.textContent = file.system === 'SIH' ? 'Hospitalar · SIH/SUS' : 'Ambulatorial · SIA/SUS';
    systemCell.append(systemPill);

    const stateCell = makeCell();
    const stateName = stateNames[file.uf] || file.uf || '—';
    stateCell.textContent = file.uf ? `${stateName} · ${file.uf}` : '—';

    const sizeCell = makeCell('bases-size-cell');
    sizeCell.textContent = formatBytes(file.size);

    const conversionCell = makeCell();
    const status = statusOf(file);
    const statusPill = document.createElement('span');
    statusPill.className = `bases-status is-${status.kind}`;
    const statusDot = document.createElement('i');
    statusDot.setAttribute('aria-hidden', 'true');
    const statusLabel = document.createElement('span');
    statusLabel.textContent = status.label;
    statusPill.append(statusDot, statusLabel);
    conversionCell.append(statusPill);

    const actionsCell = makeCell('bases-actions-cell');
    const tabulate = document.createElement('a');
    tabulate.className = 'bases-action-link';
    tabulate.href = file.converted ? 'tabular.php?stage=3' : 'tabular.php';
    tabulate.textContent = 'Tabular';
    tabulate.setAttribute('aria-label', `Selecionar ${file.name} para tabular`);
    tabulate.addEventListener('click', () => {
      try {
        localStorage.setItem('spptab-active-file-v1', file.path);
        window.dispatchEvent(new Event('spptab-active-file-change'));
      } catch (_) {}
    });
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'bases-remove-button';
    remove.textContent = 'Remover';
    remove.setAttribute('aria-label', `Remover ${file.name} da biblioteca`);
    const converting = file.conversion?.status === 'running' || file.conversion?.status === 'queued';
    if (converting) {
      remove.disabled = true;
      remove.title = 'Aguarde a conversão terminar para remover este arquivo.';
    }
    remove.addEventListener('click', () => openRemoveDialog(file));
    actionsCell.append(tabulate, remove);
    row.append(identity, systemCell, stateCell, sizeCell, conversionCell, actionsCell);
    return row;
  }

  function filteredFiles() {
    const term = search.value.trim().toLocaleLowerCase('pt-BR');
    const system = systemFilter.value;
    return files.filter((file) => {
      if (system !== 'all' && file.system !== system) return false;
      if (!term) return true;
      const status = statusOf(file).label;
      const text = [file.name, file.path, file.system, file.kind, file.uf, stateNames[file.uf], file.year, monthNames[(Number(file.month) || 1) - 1], status].join(' ').toLocaleLowerCase('pt-BR');
      return text.includes(term);
    });
  }

  function render() {
    rows.replaceChildren();
    const visible = filteredFiles();
    const fragment = document.createDocumentFragment();
    visible.forEach((file) => fragment.append(createRow(file)));
    rows.append(fragment);
    $('#totalCount').textContent = String(files.length);
    $('#siaCount').textContent = String(files.filter((file) => file.system === 'SIA').length);
    $('#sihCount').textContent = String(files.filter((file) => file.system === 'SIH').length);
    $('#convertedCount').textContent = String(files.filter((file) => file.converted).length);
    $('#libraryCountTag').textContent = `${files.length} ${files.length === 1 ? 'arquivo' : 'arquivos'}`;
    $('#visibleCount').textContent = `${visible.length} ${visible.length === 1 ? 'arquivo' : 'arquivos'}`;
    const noFiles = files.length === 0;
    loading.hidden = true;
    empty.hidden = visible.length > 0;
    if (noFiles) {
      $('#emptyTitle').textContent = 'Sua biblioteca ainda está vazia';
      $('#emptyCopy').textContent = 'Adicione arquivos DBC ambulatoriais ou hospitalares para começar a organizar suas bases.';
    } else if (visible.length === 0) {
      $('#emptyTitle').textContent = 'Nenhum arquivo encontrado';
      $('#emptyCopy').textContent = 'Altere a busca ou o sistema selecionado para ver outras bases.';
    }
    $('#librarySearch').disabled = noFiles;
    $('#systemFilter').disabled = noFiles;
  }

  function openRemoveDialog(file) {
    pendingFile = file;
    $('#removeError').hidden = true;
    $('#removeError').textContent = '';
    $('#removeFileName').textContent = `${file.name} · ${file.system} · ${String(file.month).padStart(2, '0')}/${file.year}`;
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else if (window.confirm(`Remover ${file.name}? O DBC e o DBF convertido serão excluídos deste computador.`)) removeFile();
  }

  async function removeFile() {
    if (!pendingFile || busy) return;
    busy = true;
    confirmRemove.disabled = true;
    cancelRemove.disabled = true;
    confirmRemove.textContent = 'Removendo…';
    clearNotice();
    try {
      const result = await request({action:'delete_file', path:pendingFile.path});
      files = Array.isArray(result.files) ? result.files : files.filter((file) => file.path !== pendingFile.path);
      try {
        if (localStorage.getItem('spptab-active-file-v1') === pendingFile.path) localStorage.removeItem('spptab-active-file-v1');
        window.dispatchEvent(new Event('spptab-active-file-change'));
      } catch (_) {}
      if (dialog.open) dialog.close();
      setNotice(`${pendingFile.name} foi removido da biblioteca e do computador.`, 'success');
      pendingFile = null;
      render();
    } catch (error) {
      const message = error.message || 'Não foi possível remover o arquivo.';
      if (dialog.open) {
        $('#removeError').textContent = message;
        $('#removeError').hidden = false;
      } else {
        setNotice(message, 'error');
      }
    } finally {
      busy = false;
      confirmRemove.disabled = false;
      cancelRemove.disabled = false;
      confirmRemove.textContent = 'Remover arquivo';
    }
  }

  async function loadLibrary() {
    loading.hidden = false;
    empty.hidden = true;
    try {
      const data = await request({action:'catalog'});
      files = Array.isArray(data.files) ? data.files : [];
      render();
    } catch (error) {
      loading.hidden = true;
      $('#emptyTitle').textContent = 'Não foi possível abrir a biblioteca';
      $('#emptyCopy').textContent = error.message || 'Confira se o servidor local está ativo e tente novamente.';
      empty.hidden = false;
      empty.querySelector('.button').hidden = true;
      $('#visibleCount').textContent = 'Erro ao carregar';
      setNotice(error.message || 'Não foi possível carregar os arquivos.', 'error');
    }
  }

  search.addEventListener('input', render);
  systemFilter.addEventListener('change', render);
  confirmRemove.addEventListener('click', removeFile);
  cancelRemove.addEventListener('click', () => { if (!busy && dialog.open) dialog.close(); });
  dialog.addEventListener('cancel', (event) => { if (busy) event.preventDefault(); });
  loadLibrary();
})();
