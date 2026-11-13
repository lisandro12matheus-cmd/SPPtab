(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const yearSelect = $('hppYear');
  const monthSelect = $('hppMonth');
  const runButton = $('hppRun');
  const availability = $('hppAvailability');
  const progressPanel = $('hppProgress');
  const resultsPanel = $('hppResults');
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const reportId = 'cnes-hospitais-pequeno-porte-filantropicos';
  let currentResult = null;
  let requestNumber = 0;
  let page = 1;
  const monthNames = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho','Agosto','Setembro','Outubro','Novembro','Dezembro'];

  async function api(payload) {
    const response = await fetch('api.php', {
      method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json','X-SPPtab-CSRF':csrf},
      body:JSON.stringify(payload)
    });
    const body = await response.text();
    let data;
    try { data = JSON.parse(body); } catch (_) { throw new Error(body.trim() || 'O serviço local respondeu sem dados. Atualize a página e tente novamente.'); }
    if (!response.ok || !data?.ok) throw new Error(data?.error || 'Não foi possível concluir a consulta.');
    return data;
  }

  function setAvailability(message, isError = false) {
    availability.textContent = message;
    availability.classList.toggle('is-error', isError);
  }

  function setProgress(stage, percent, message = '') {
    $('hppStage').textContent = stage || 'Consulta em andamento';
    const value = Math.max(0, Math.min(100, Number(percent) || 0));
    $('hppPercent').textContent = `${Math.round(value)}%`;
    $('hppProgressFill').style.width = `${value}%`;
    $('hppMessage').textContent = message || 'A consulta continua no computador onde o TabulaSUS está aberto.';
  }

  async function loadMonths(preferred = 9) {
    const request = ++requestNumber;
    const year = Number(yearSelect.value);
    monthSelect.disabled = true;
    monthSelect.replaceChildren(new Option('Consultando o CNES…', ''));
    runButton.disabled = true;
    setAvailability(`Verificando quais meses de ${year} têm arquivo CNES em todas as UFs.`);
    try {
      const data = await api({action:'predefined_filter_options',report:reportId,year});
      if (request !== requestNumber) return;
      const months = [...new Set((data.months || []).map(Number).filter((month) => month >= 1 && month <= 12))].sort((a,b) => a-b);
      monthSelect.replaceChildren();
      if (!months.length) {
        monthSelect.add(new Option('Nenhuma competência nacional disponível', ''));
        monthSelect.disabled = true;
        setAvailability(`O CNES ainda não publicou arquivos de ${year} para todas as 27 UFs.`);
        return;
      }
      for (const month of months) monthSelect.add(new Option(monthNames[month - 1], String(month)));
      monthSelect.value = months.includes(Number(preferred)) ? String(preferred) : String(months[months.length - 1]);
      monthSelect.disabled = false;
      runButton.disabled = false;
      setAvailability(`${months.length} competência(s) nacional(is) disponível(is) em ${year}. O levantamento vai conferir os arquivos antes de calcular.`);
    } catch (error) {
      if (request !== requestNumber) return;
      monthSelect.replaceChildren(new Option('Não foi possível carregar os meses', ''));
      monthSelect.disabled = true;
      setAvailability(error.message || 'Não foi possível consultar o CNES agora.', true);
    }
  }

  function countBy(rows, field) {
    const counts = new Map();
    for (const row of rows) {
      const key = String(row[field] ?? '');
      counts.set(key, (counts.get(key) || 0) + 1);
    }
    return counts;
  }

  function setSelectOptions(select, placeholder, values, selectedValue = '') {
    select.replaceChildren(new Option(placeholder, ''));
    for (const item of values) select.add(new Option(item.label, item.value));
    select.value = values.some((item) => item.value === selectedValue) ? selectedValue : '';
  }

  function populateFilters() {
    if (!currentResult) return;
    const rows = currentResult.rows || [];
    const stateValue = $('hppUf').value;
    const municipalityValue = $('hppMunicipality').value;
    const typeValue = $('hppUnitType').value;
    const natureValue = $('hppLegalNature').value;
    const bandValue = $('hppBedBand').value;

    const states = [...countBy(rows, 'uf').entries()].map(([value,count]) => {
      const row = rows.find((item) => item.uf === value);
      return {value,label:`${row?.stateName || value} (${value}) · ${count.toLocaleString('pt-BR')}`};
    }).sort((a,b) => a.label.localeCompare(b.label,'pt-BR'));
    setSelectOptions($('hppUf'),'Todas as UFs',states,stateValue);

    const municipalityRows = stateValue ? rows.filter((row) => row.uf === stateValue) : rows;
    const municipalities = [...countBy(municipalityRows, 'municipalityCode').entries()].map(([value,count]) => {
      const row = municipalityRows.find((item) => item.municipalityCode === value);
      const stateLabel = stateValue ? '' : ` (${row?.uf || ''})`;
      return {value,label:`${row?.municipalityName || value}${stateLabel} · ${count.toLocaleString('pt-BR')}`};
    }).sort((a,b) => a.label.localeCompare(b.label,'pt-BR'));
    setSelectOptions($('hppMunicipality'),stateValue ? 'Todos os municípios' : 'Selecione uma UF primeiro',municipalities,municipalityValue);
    $('hppMunicipality').disabled = !stateValue || !municipalities.length;

    const types = [...countBy(rows, 'unitTypeCode').entries()].map(([value,count]) => {
      const row = rows.find((item) => item.unitTypeCode === value);
      return {value,label:`${row?.unitTypeName || value} · ${count.toLocaleString('pt-BR')}`};
    }).sort((a,b) => a.label.localeCompare(b.label,'pt-BR'));
    setSelectOptions($('hppUnitType'),'Todos os tipos',types,typeValue);

    const natures = [...countBy(rows, 'legalNatureCode').entries()].map(([value,count]) => {
      const row = rows.find((item) => item.legalNatureCode === value);
      return {value,label:`${row?.legalNatureName || value} · ${count.toLocaleString('pt-BR')}`};
    }).sort((a,b) => a.label.localeCompare(b.label,'pt-BR'));
    setSelectOptions($('hppLegalNature'),'Todas as naturezas',natures,natureValue);

    const bands = [...countBy(rows, 'bedBandCode').entries()].map(([value,count]) => {
      const row = rows.find((item) => item.bedBandCode === value);
      return {value,label:`${row?.bedBandName || value} · ${count.toLocaleString('pt-BR')}`};
    }).sort((a,b) => a.value.localeCompare(b.value,'pt-BR',{numeric:true}));
    setSelectOptions($('hppBedBand'),'Todas as faixas',bands,bandValue);
  }

  function matchingRows() {
    const rows = currentResult?.rows || [];
    const query = $('hppSearch').value.trim().toLocaleLowerCase('pt-BR');
    const uf = $('hppUf').value;
    const municipality = $('hppMunicipality').value;
    const type = $('hppUnitType').value;
    const nature = $('hppLegalNature').value;
    const band = $('hppBedBand').value;
    return rows.filter((row) => {
      if (uf && row.uf !== uf) return false;
      if (municipality && row.municipalityCode !== municipality) return false;
      if (type && row.unitTypeCode !== type) return false;
      if (nature && row.legalNatureCode !== nature) return false;
      if (band && row.bedBandCode !== band) return false;
      if (!query) return true;
      const haystack = [row.establishmentName,row.cnes,row.municipalityName,row.municipalityCode,row.uf,row.stateName,row.unitTypeName,row.legalNatureName,row.legalNatureCode,row.bedBandName].join(' ').toLocaleLowerCase('pt-BR');
      return haystack.includes(query);
    });
  }

  function sortedRows(rows) {
    const sort = $('hppSort').value;
    const copy = [...rows];
    const compareText = (a,b,field) => String(a[field] || '').localeCompare(String(b[field] || ''),'pt-BR',{sensitivity:'base'});
    if (sort === 'name-asc') copy.sort((a,b) => compareText(a,b,'establishmentName') || a.cnes.localeCompare(b.cnes));
    else if (sort === 'beds-desc') copy.sort((a,b) => Number(b.bedsTotal) - Number(a.bedsTotal) || compareText(a,b,'stateName'));
    else if (sort === 'beds-asc') copy.sort((a,b) => Number(a.bedsTotal) - Number(b.bedsTotal) || compareText(a,b,'stateName'));
    else copy.sort((a,b) => compareText(a,b,'stateName') || compareText(a,b,'municipalityName') || compareText(a,b,'establishmentName') || a.cnes.localeCompare(b.cnes));
    return copy;
  }

  function renderKpis(rows) {
    const totalBeds = rows.reduce((sum,row) => sum + (Number(row.bedsTotal) || 0),0);
    const values = [
      ['HOSPITAIS NO RECORTE',rows.length,0],
      ['UFS COM REGISTROS',new Set(rows.map((row) => row.uf)).size,0],
      ['LEITOS EXISTENTES',totalBeds,0],
      ['MÉDIA DE LEITOS',rows.length ? totalBeds / rows.length : 0,1],
    ];
    const host = $('hppKpis'); host.replaceChildren();
    for (const [label,number,decimals] of values) {
      const card = document.createElement('article'); card.className = 'hpp-kpi';
      const title = document.createElement('span'); title.textContent = label;
      const value = document.createElement('strong'); value.textContent = Number(number).toLocaleString('pt-BR',{minimumFractionDigits:decimals,maximumFractionDigits:decimals});
      card.append(title,value); host.append(card);
    }
  }

  function renderTable(rows) {
    const columns = currentResult.columns || [];
    const pageSize = Math.max(1,Number($('hppPageSize').value) || 100);
    const pageCount = Math.max(1,Math.ceil(rows.length / pageSize));
    page = Math.min(Math.max(1,page),pageCount);
    const pageRows = rows.slice((page - 1) * pageSize,page * pageSize);
    $('hppPageInfo').textContent = `Página ${page.toLocaleString('pt-BR')} de ${pageCount.toLocaleString('pt-BR')}`;
    $('hppPagePrevious').disabled = page <= 1;
    $('hppPageNext').disabled = page >= pageCount;

    const head = $('hppHead'); head.replaceChildren();
    const headerRow = document.createElement('tr');
    for (const column of columns) {
      const th = document.createElement('th'); th.scope = 'col'; th.textContent = column.label || column.id; headerRow.append(th);
    }
    head.append(headerRow);

    const body = $('hppBody'); body.replaceChildren();
    if (!rows.length) {
      const tr = document.createElement('tr'); const td = document.createElement('td');
      td.colSpan = Math.max(1,columns.length); td.className = 'hpp-empty'; td.textContent = currentResult.emptyStateMessage || 'Nenhum hospital corresponde aos filtros selecionados.';
      tr.append(td); body.append(tr);
    } else for (const row of pageRows) {
      const tr = document.createElement('tr');
      for (const column of columns) {
        const td = document.createElement('td');
        if (column.type === 'number') td.classList.add('is-number');
        const value = row[column.field || column.primaryField || ''];
        const primary = column.primaryField ? row[column.primaryField] : null;
        const secondary = column.secondaryField ? row[column.secondaryField] : null;
        if (primary !== null && primary !== undefined) {
          const strong = document.createElement('strong'); strong.textContent = String(primary); td.append(strong);
          if (secondary) { const small = document.createElement('small'); small.textContent = `${column.secondaryPrefix || ''}${secondary}`; td.append(small); }
        } else {
          td.textContent = value === null || value === undefined ? '' : column.type === 'number' ? Number(value).toLocaleString('pt-BR') : String(value);
          if (column.secondaryField && secondary) { const small = document.createElement('small'); small.textContent = String(secondary); td.append(small); }
        }
        tr.append(td);
      }
      body.append(tr);
    }

    const foot = $('hppFoot'); foot.replaceChildren();
    const totalRow = document.createElement('tr');
    columns.forEach((column,index) => {
      const td = document.createElement('td');
      if (index === 0) td.textContent = `Total · ${rows.length.toLocaleString('pt-BR')} hospitais`;
      else if (column.totalField) {
        td.classList.add('is-number');
        td.textContent = rows.reduce((sum,row) => sum + (Number(row[column.totalField]) || 0),0).toLocaleString('pt-BR');
      }
      totalRow.append(td);
    });
    foot.append(totalRow);
  }

  function renderFilteredResult() {
    if (!currentResult) return;
    const rows = sortedRows(matchingRows());
    const total = (currentResult.rows || []).length;
    const monthName = monthNames[(Number(currentResult.month) || 1) - 1];
    $('hppResultScope').textContent = `Brasil · ${monthName} de ${currentResult.year} · ${rows.length.toLocaleString('pt-BR')} de ${total.toLocaleString('pt-BR')} hospitais`;
    $('hppTableHint').textContent = `${rows.length.toLocaleString('pt-BR')} de ${total.toLocaleString('pt-BR')} hospitais no recorte · página ${page.toLocaleString('pt-BR')}`;
    renderKpis(rows);
    renderTable(rows);
    $('hppTableHint').textContent = `${rows.length.toLocaleString('pt-BR')} de ${total.toLocaleString('pt-BR')} hospitais no recorte · página ${page.toLocaleString('pt-BR')}`;
  }

  function renderResult(result) {
    currentResult = result;
    resultsPanel.hidden = false;
    $('hppSearch').value = '';
    $('hppSort').value = 'state-asc';
    for (const id of ['hppUf','hppMunicipality','hppUnitType','hppLegalNature','hppBedBand']) $(id).value = '';
    page = 1;
    populateFilters();
    renderFilteredResult();
    const notes = $('hppNotes'); notes.replaceChildren();
    for (const note of result.notes || []) { const p = document.createElement('p'); p.textContent = note; notes.append(p); }
    resultsPanel.scrollIntoView({behavior:'smooth',block:'start'});
  }

  async function runReport() {
    if (!yearSelect.value || !monthSelect.value) return;
    runButton.disabled = true; yearSelect.disabled = true; monthSelect.disabled = true;
    resultsPanel.hidden = true; progressPanel.hidden = false;
    progressPanel.setAttribute('aria-busy','true');
    setAvailability('Levantamento iniciado. Esta consulta lê os arquivos mensais das 27 UFs.');
    setProgress('Preparando a consulta nacional',1);
    try {
      let job = await api({action:'tabulate_start',predefinedReport:reportId,year:Number(yearSelect.value),month:Number(monthSelect.value)});
      if (!job.job_id) throw new Error('Não foi possível iniciar a leitura em segundo plano.');
      const jobId = job.job_id;
      while (true) {
        await new Promise((resolve) => setTimeout(resolve,1200));
        job = await api({action:'tabulate_status',job_id:jobId});
        setProgress(job.stage,job.progress,job.message);
        if (job.status === 'error') throw new Error(job.message || 'A leitura do CNES não foi concluída.');
        if (job.status === 'done') {
          if (!job.result?.ok) throw new Error('O relatório terminou sem um resultado válido.');
          renderResult(job.result);
          setAvailability('Consulta concluída com os arquivos oficiais do CNES.');
          break;
        }
      }
    } catch (error) {
      setAvailability(error.message || 'Não foi possível concluir o levantamento.',true);
    } finally {
      progressPanel.hidden = true; progressPanel.setAttribute('aria-busy','false');
      yearSelect.disabled = false; monthSelect.disabled = false; runButton.disabled = !monthSelect.value;
    }
  }

  function csvEscape(value) {
    let text = value === null || value === undefined ? '' : String(value);
    if (/^[=+@\-\t\r]/.test(text)) text = `'${text}`;
    return `"${text.replaceAll('"','""')}"`;
  }

  function exportCsv() {
    if (!currentResult) return;
    const rows = sortedRows(matchingRows());
    const headers = ['CNES','Estabelecimento','Município','Código IBGE do município','UF','Estado','Tipo de hospital','Grupo da natureza jurídica','Natureza jurídica específica','Código da natureza jurídica','Faixa de leitos','Código da faixa de leitos','Leitos cirúrgicos','Leitos clínicos','Leitos complementares','Total de leitos','Competência'];
    const fields = ['cnes','establishmentName','municipalityName','municipalityCode','uf','stateName','unitTypeName','legalNatureGroupName','legalNatureName','legalNatureCode','bedBandName','bedBandCode','bedsSurgical','bedsClinical','bedsComplementary','bedsTotal','competence'];
    const lines = [headers.map(csvEscape).join(';')];
    for (const row of rows) lines.push(fields.map((field) => csvEscape(row[field])).join(';'));
    const blob = new Blob(['\ufeff',lines.join('\r\n')],{type:'text/csv;charset=utf-8'});
    const url = URL.createObjectURL(blob); const link = document.createElement('a');
    link.href = url; link.download = `hospitais-pequeno-porte-sem-fins-lucrativos-${currentResult.year}-${String(currentResult.month).padStart(2,'0')}.csv`;
    document.body.append(link); link.click(); link.remove(); URL.revokeObjectURL(url);
  }

  function updateResults(resetPage = true) {
    if (resetPage) page = 1;
    renderFilteredResult();
  }

  const currentYear = new Date().getFullYear();
  for (let year = currentYear; year >= 2005; year--) yearSelect.add(new Option(String(year),String(year)));
  yearSelect.value = String(currentYear);
  yearSelect.addEventListener('change',() => loadMonths(9));
  runButton.addEventListener('click',runReport);
  $('hppExport').addEventListener('click',exportCsv);
  $('hppSearch').addEventListener('input',() => updateResults());
  $('hppUf').addEventListener('change',() => { populateFilters(); updateResults(); });
  for (const id of ['hppMunicipality','hppUnitType','hppLegalNature','hppBedBand','hppSort']) $(id).addEventListener('change',() => updateResults());
  $('hppClearFilters').addEventListener('click',() => {
    $('hppSearch').value = '';
    for (const id of ['hppUf','hppMunicipality','hppUnitType','hppLegalNature','hppBedBand']) $(id).value = '';
    $('hppSort').value = 'state-asc';
    populateFilters(); updateResults();
  });
  $('hppPagePrevious').addEventListener('click',() => { page = Math.max(1,page - 1); updateResults(false); });
  $('hppPageNext').addEventListener('click',() => { page += 1; updateResults(false); });
  $('hppPageSize').addEventListener('change',() => updateResults());
  loadMonths(currentYear === 2026 ? 9 : 1);
})();
