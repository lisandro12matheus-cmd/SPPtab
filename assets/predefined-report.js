(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const yearSelect = $('reportYear');
  const monthSelect = $('reportMonth');
  const monthPicker = $('reportMonthPicker');
  const monthPickerTrigger = $('reportMonthTrigger');
  const monthPickerTriggerText = $('reportMonthTriggerText');
  const monthPickerMenu = $('reportMonthMenu');
  const monthPickerCount = $('reportMonthCount');
  const monthPickerOptions = $('reportMonthOptions');
  const ufSelect = $('reportUf');
  const municipalitySelect = $('reportMunicipality');
  const addFilterSelect = $('addReportFilter');
  const addedFilterRows = $('reportAdditionalFilters');
  const setupDialog = $('reportSetupDialog');
  const openButton = $('openReport');
  const availability = $('reportAvailability');
  const loader = $('reportLoader');
  const stage = $('reportStage');
  const detail = $('reportDetail');
  const progress = $('reportProgress');
  const progressFill = $('reportProgressFill');
  const progressLabel = $('reportProgressLabel');
  const downloadQueue = $('reportDownloadQueue');
  const downloadHeading = $('reportDownloadHeading');
  const downloadFiles = $('reportDownloadFiles');
  const downloadTasks = new Map();
  const notice = $('reportNotice');
  const empty = $('reportEmpty');
  const resultPanel = $('reportResult');
  const catalogPanel = $('predefinedCatalog');
  const workspacePanel = $('reportWorkspace');
  const localFiles = new Map();
  const results = new Map();
  const reportDefaults = new Map();
  const reportDefaultRequests = new Map();
  let allRows = [];
  let activeResult = null;
  let activeView = 'summary';
  let activeCnes = '';
  let activeAih = '';
  let activeYear = 0;
  let activeMonth = 0;
  let activeMonths = [];
  let reportMonths = [];
  let reportControlsReady = false;
  let filterRequest = 0;
  let competencyRequest = 0;
  let activeFilterTypes = [];
  let filterCategories = {};
  let columnFilters = new Map();
  let sortState = null;
  let columnFilterMenu = null;
  let tablePage = 1;
  let tablePageSize = 100;

  const monthNames = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'];
  const stateNames = { AC:'Acre', AL:'Alagoas', AP:'Amapá', AM:'Amazonas', BA:'Bahia', CE:'Ceará', DF:'Distrito Federal', ES:'Espírito Santo', GO:'Goiás', MA:'Maranhão', MT:'Mato Grosso', MS:'Mato Grosso do Sul', MG:'Minas Gerais', PA:'Pará', PB:'Paraíba', PR:'Paraná', PE:'Pernambuco', PI:'Piauí', RJ:'Rio de Janeiro', RN:'Rio Grande do Norte', RS:'Rio Grande do Sul', RO:'Rondônia', RR:'Roraima', SC:'Santa Catarina', SP:'São Paulo', SE:'Sergipe', TO:'Tocantins' };
  const stateCodes = { RO:'11', AC:'12', AM:'13', RR:'14', PA:'15', AP:'16', TO:'17', MA:'21', PI:'22', CE:'23', RN:'24', PB:'25', PE:'26', AL:'27', SE:'28', BA:'29', MG:'31', ES:'32', RJ:'33', SP:'35', PR:'41', SC:'42', RS:'43', MS:'50', MT:'51', GO:'52', DF:'53' };
  const siaFilterDefinitions = {
    manager: { label:'Gestor da produção', field:'managerCode', nameField:'managerName', allLabel:'Todos os gestores', responseKey:'managers', queryKey:'gestor', sourceLabel:'Arquivo DATASUS · SIA/PA' },
    legalNature: { label:'Natureza jurídica', field:'legalNatureCode', nameField:'legalNatureName', allLabel:'Todas as naturezas jurídicas', responseKey:'legalNatures', queryKey:'natureza', sourceLabel:'Arquivo DATASUS · SIA/PA' },
    managementType: { label:'Tipo de gestão', field:'managementTypeCode', nameField:'managementTypeName', allLabel:'Todos os tipos de gestão', responseKey:'managementTypes', queryKey:'tipo_gestao', sourceLabel:'Arquivo DATASUS · SIA/PA' },
    providerType: { label:'Tipo do prestador (público, privado etc.)', field:'providerTypeCode', nameField:'providerTypeName', allLabel:'Todos os tipos de prestador', responseKey:'providerTypes', queryKey:'tipo_prestador', sourceLabel:'Arquivo DATASUS · SIA/PA' },
    complexity: { label:'Complexidade do procedimento', field:'complexityCode', nameField:'complexityName', allLabel:'Todas as complexidades', responseKey:'complexities', queryKey:'complexidade', sourceLabel:'Arquivo DATASUS · SIA/PA' },
    financing: { label:'Financiamento (MAC/FAEC)', field:'financingCode', nameField:'financingName', allLabel:'Todos os financiamentos', responseKey:'financings', queryKey:'financiamento', sourceLabel:'Arquivo DATASUS · SIA/PA' }
  };
  const sihFilterDefinitions = {
    manager: { label:'Gestor da produção', field:'UF_ZI', nameField:'UF_ZIName', responseKey:'managers', queryKey:'gestor', sourceLabel:'Arquivo DATASUS · SIH (município gestor)' },
    financing: { label:'Financiamento (MAC/FAEC)', field:'FINANC', nameField:'FINANCName', responseKey:'financings', queryKey:'financiamento', sourceLabel:'Arquivo DATASUS · SIH' },
    faecType: { label:'Subtipo do FAEC', field:'FAEC_TP', nameField:'FAEC_TPName', responseKey:'faecTypes', queryKey:'faec', sourceLabel:'Arquivo DATASUS · SIH' },
    complexity: { label:'Complexidade', field:'COMPLEX', nameField:'COMPLEXName', responseKey:'complexities', queryKey:'complexidade', sourceLabel:'Arquivo DATASUS · SIH' },
    legalNature: { label:'Natureza jurídica', field:'NAT_JUR', nameField:'NAT_JURName', responseKey:'legalNatures', queryKey:'natureza', sourceLabel:'Arquivo DATASUS · SIH' },
    providerNature: { label:'Natureza do prestador', field:'NATUREZA', nameField:'NATUREZAName', responseKey:'providerNatures', queryKey:'natureza_prestador', sourceLabel:'Arquivo DATASUS · SIH' },
    management: { label:'Tipo de gestão', field:'GESTAO', nameField:'GESTAOName', responseKey:'managementTypes', queryKey:'gestao', sourceLabel:'Arquivo DATASUS · SIH' },
    admissionType: { label:'Caráter de atendimento', field:'CAR_INT', nameField:'CAR_INTName', responseKey:'admissionTypes', queryKey:'carater', sourceLabel:'Arquivo DATASUS · SIH' }
  };
  const sihSpFilterDefinitions = {
    manager: { label:'Gestor da produção', field:'SP_GESTOR', nameField:'SP_GESTORName', responseKey:'managers', queryKey:'gestor', sourceLabel:'Arquivo DATASUS · SIH/SP' },
    professionalCbo: { label:'CBO do profissional', field:'professionalCboCode', nameField:'professionalCboName', responseKey:'professionalCbos', queryKey:'cbo', sourceLabel:'Arquivo DATASUS · SIH/SP' },
    cnesManagement: { label:'Tipo de gestão · CNES', field:'cnesManagementCode', nameField:'cnesManagementName', responseKey:'cnesManagementTypes', queryKey:'cnes_gestao', sourceLabel:'CNES na competência · cadastro atual se ausente' },
    cnesNatureGroup: { label:'Natureza jurídica · grupo CNES', field:'cnesNatureGroupCode', nameField:'cnesNatureGroupName', responseKey:'cnesNatureGroups', queryKey:'cnes_grupo_natureza', sourceLabel:'CNES na competência · cadastro atual se ausente' },
    cnesLegalNature: { label:'Natureza jurídica detalhada · CNES', field:'cnesLegalNatureCode', nameField:'cnesLegalNatureName', responseKey:'cnesLegalNatures', queryKey:'cnes_natureza', sourceLabel:'CNES na competência · cadastro atual se ausente' },
    cnesHospitalSUS: { label:'Atendimento hospitalar SUS · CNES atual', field:'cnesHospitalSUSCode', nameField:'cnesHospitalSUSName', responseKey:'cnesHospitalSUS', queryKey:'cnes_atende_sus', sourceLabel:'Cadastro atual · pode diferir da competência histórica' }
  };
  const sihOccupancyFilterDefinitions = {
    ...sihFilterDefinitions,
    specialty: { label:'Especialidade do leito', field:'ESPEC', nameField:'ESPECName', responseKey:'specialties', queryKey:'especialidade' }
  };
  const reportConfigurations = {
    'sia-pa-producao': {
      id:'sia-pa-producao', system:'sia', systemCode:'SIA', kind:'PA', systemLabel:'SIA/SUS', sourceLabel:'produção ambulatorial',
      workspaceTitle:'Produção Ambulatorial · SIA/SUS', introLabel:'PRODUÇÃO AMBULATORIAL · SIA/SUS', introTitle:'Produção ambulatorial por estabelecimento.',
      introDescription:'Produção ambulatorial por competência, com detalhamento por procedimento SIGTAP.',
      setupTitle:'Produção ambulatorial por estabelecimento', setupDescription:'Escolha a origem e a competência. Vários meses exigem bases já baixadas. Os filtros adicionais são opcionais.',
      emptyMessage:'Escolha a UF e a competência. Município, gestão, tipo de prestador, natureza jurídica, complexidade e financiamento são opcionais.',
      municipalityLabel:'MUNICÍPIO',
      filterNote:'O município e os demais filtros valem para toda a consulta. Use Ctrl no Windows ou Command no Mac para marcar várias categorias no mesmo filtro. Sem seleção, todas são consideradas; filtros diferentes são combinados.',
      methodTitle:'Como ler glosas e rejeições:', methodText:' glosas são a diferença positiva entre o apresentado e o aprovado. A base ambulatorial não traz um total independente de rejeições; esse indicador conta linhas apresentadas com quantidade aprovada igual a zero.',
      detailPrefix:'Procedimentos SIGTAP', countMetric:'qtd_aprovada', countLabel:'QUANTIDADE APROVADA', valueMetric:'valor_aprovado', valueLabel:'VALOR APROVADO',
      summaryTitle:'Produção por estabelecimento', detailTitlePrefix:'Procedimentos SIGTAP', detailCountLabel:'COMPOSIÇÕES SIGTAP',
      filters:siaFilterDefinitions, tableSearchSummary:'Buscar estabelecimento ou CNES', tableSearchDetail:'Buscar código SIGTAP ou procedimento'
    },
    'sih-rd-producao': {
      id:'sih-rd-producao', system:'sih', systemCode:'SIH', kind:'RD', systemLabel:'SIH/SUS', sourceLabel:'produção hospitalar',
      workspaceTitle:'Produção Hospitalar · SIH/SUS', introLabel:'PRODUÇÃO HOSPITALAR · SIH/SUS', introTitle:'Produção hospitalar por estabelecimento.',
      introDescription:'AIHs e valores por hospital, com detalhamento do procedimento principal, complexidade e financiamento.',
      setupTitle:'Produção hospitalar por estabelecimento', setupDescription:'Escolha a UF e a competência das AIHs. Vários meses exigem bases já baixadas. Município e filtros adicionais são opcionais.',
      emptyMessage:'Escolha a UF e a competência. Município da internação, gestor da produção, financiamento (MAC/FAEC), subtipo FAEC, complexidade, natureza jurídica, natureza do prestador, gestão e caráter de atendimento são opcionais.',
      municipalityLabel:'MUNICÍPIO DA INTERNAÇÃO',
      filterNote:'O município selecionado representa o local da internação. Gestor da produção usa o Município Gestor oficial (UF_ZI) das AIHs. Use Ctrl no Windows ou Command no Mac para marcar várias categorias no mesmo filtro. Sem seleção, todas são consideradas; filtros diferentes são combinados.',
      methodTitle:'Como ler os dados hospitalares:', methodText:' o relatório usa AIHs processadas no SIH/RD. Renovações de longa permanência podem aparecer em competências sucessivas; rejeições RJ/ER não entram nesta soma.',
      detailPrefix:'Procedimento principal', countMetric:'qtd_aih', countLabel:'AIHs PROCESSADAS', valueMetric:'valor_total', valueLabel:'VALOR TOTAL DAS AIHs',
      summaryTitle:'Produção hospitalar por estabelecimento', detailTitlePrefix:'Composição da AIH', detailCountLabel:'COMBINAÇÕES DE PROCEDIMENTO',
      filters:sihFilterDefinitions, tableSearchSummary:'Buscar hospital ou CNES', tableSearchDetail:'Buscar código SIGTAP ou procedimento'
    },
    'sih-rd-rejeicoes': {
      id:'sih-rd-rejeicoes', system:'sih', systemCode:'SIH', kind:'RJ', requiredKinds:['RJ'], optionalKinds:['ER'], systemLabel:'SIH/SUS', sourceLabel:'AIHs rejeitadas',
      workspaceTitle:'AIHs rejeitadas · SIH/SUS', introLabel:'REJEIÇÕES HOSPITALARES · SIH/SUS', introTitle:'AIHs rejeitadas por estabelecimento.',
      introDescription:'Quantidade e valores associados às AIHs rejeitadas, com os motivos registrados no processamento.',
      setupTitle:'AIHs rejeitadas por estabelecimento', setupDescription:'Escolha a competência. Vários meses exigem bases já baixadas. Os filtros são opcionais.',
      emptyMessage:'Escolha a UF e a competência. Município da internação, gestor da produção, financiamento (MAC/FAEC), subtipo FAEC, complexidade, natureza jurídica, natureza do prestador, gestão e caráter de atendimento são opcionais.',
      municipalityLabel:'MUNICÍPIO DA INTERNAÇÃO',
      filterNote:'O município selecionado representa o local da internação. Gestor da produção usa o Município Gestor oficial (UF_ZI) das AIHs rejeitadas. Use Ctrl no Windows ou Command no Mac para marcar várias categorias no mesmo filtro. Sem seleção, todas são consideradas; filtros diferentes são combinados.',
      methodTitle:'Como interpretar os valores:', methodText:' o relatório usa os valores registrados na própria base SIH/RJ. Os motivos vêm do SIH/ER e uma AIH pode ter mais de uma crítica, sem duplicar seus valores.',
      detailPrefix:'Composição da AIH', countMetric:'qtd_aih_rejeitada', countLabel:'AIHs REJEITADAS', valueMetric:'valor_rejeitado', valueLabel:'VALOR REJEITADO',
      summaryTitle:'AIHs rejeitadas por estabelecimento', detailTitlePrefix:'AIHs rejeitadas · composição e críticas', detailCountLabel:'COMBINAÇÕES DE PROCEDIMENTO',
      filters:sihFilterDefinitions, tableSearchSummary:'Buscar hospital ou CNES', tableSearchDetail:'Buscar procedimento ou motivo da rejeição'
    },
    'sih-rd-ocupacao': {
      id:'sih-rd-ocupacao', system:'sih', systemCode:'SIH', kind:'RD', requiredKinds:['RD','RJ'], optionalKinds:['ER'], kindsByView:{services:['SP']},
      systemLabel:'SIH/SUS · CNES', sourceLabel:'ocupação de leitos', tableMode:'occupancy', defaultMunicipalityCode:'150140',
      workspaceTitle:'Ocupação de leitos · SIH/SUS', introLabel:'OCUPAÇÃO DE LEITOS · SIH/SUS', introTitle:'Ocupação de leitos hospitalares.',
      introDescription:'Internações, diárias, rejeições e capacidade SUS por estabelecimento, com ligação às AIHs e aos serviços profissionais.',
      setupTitle:'Ocupação de leitos por estabelecimento', setupDescription:'Escolha a UF e a competência. Vários meses exigem bases já baixadas. Município e filtros adicionais são opcionais.',
      emptyMessage:'Escolha a UF e a competência. Município, gestor da produção, especialidade, financiamento, complexidade, natureza jurídica e demais filtros são opcionais.',
      municipalityLabel:'MUNICÍPIO DA INTERNAÇÃO',
      filterNote:'Os filtros selecionados são aplicados às AIHs processadas e rejeitadas. Gestor da produção usa o Município Gestor oficial (UF_ZI). Use Ctrl no Windows ou Command no Mac para marcar várias categorias no mesmo filtro. Sem seleção, todas são consideradas; filtros diferentes são combinados.',
      methodTitle:'Como interpretar a ocupação:', methodText:' as diárias registradas vêm das AIHs processadas no SIH/RD. As rejeições entram apenas no saldo potencial, sem serem tratadas como internações confirmadas. A quantidade de leitos vem da consulta atual ao CNES e pode não corresponder exatamente à competência histórica.',
      countMetric:'aihCount', countLabel:'AIHs PROCESSADAS', valueMetric:'dailyCount', valueLabel:'DIÁRIAS SIH',
      summaryTitle:'Ocupação por estabelecimento', detailTitlePrefix:'AIHs e permanência', detailCountLabel:'AIHs DA UNIDADE',
      filters:sihOccupancyFilterDefinitions, tableSearchSummary:'Buscar hospital ou CNES', tableSearchDetail:'Buscar AIH, procedimento ou motivo'
    },
    'sih-sp-profissionais': {
      id:'sih-sp-profissionais', system:'sih', systemCode:'SIH', kind:'SP', systemLabel:'SIH/SUS · SP', sourceLabel:'serviços profissionais',
      tableMode:'flat', defaultMunicipalityCode:'150140',
      workspaceTitle:'Serviços Profissionais · SIH/SUS', introLabel:'SERVIÇOS PROFISSIONAIS · SIH/SUS', introTitle:'Produção profissional por AIH.',
      introDescription:'Atos e valores profissionais por autorização, procedimento, estabelecimento e profissional executor.',
      setupTitle:'Serviços profissionais por AIH', setupDescription:'Escolha a UF e a competência. Vários meses exigem bases já baixadas. O recorte inicial mostra Belém, Pará.',
      emptyMessage:'Escolha a UF e a competência. Município, gestor da produção, CBO, tipo de gestão, natureza jurídica e atendimento hospitalar SUS são opcionais.',
      municipalityLabel:'MUNICÍPIO DE ATENDIMENTO',
      filterNote:'O município representa o local de atendimento. Gestor e CBO vêm do SIH/SP. Como o SP não traz tipo de gestão nem natureza jurídica, esses filtros usam o CNES da mesma competência e recorrem ao cadastro atual quando não há registro histórico. O atendimento hospitalar SUS usa o cadastro atual.',
      methodTitle:'Como ler os valores profissionais:', methodText:' são somados os valores SP e seus complementos federais e locais. A quantidade de atos é contada uma vez por AIH, procedimento e CNS, mesmo quando há mais de um tipo de valor na base.',
      countMetric:'acts', countLabel:'ATOS REGISTRADOS', valueMetric:'value', valueLabel:'VALOR DOS SERVIÇOS',
      summaryTitle:'Serviços profissionais por AIH', detailTitlePrefix:'Serviços profissionais', detailCountLabel:'LANÇAMENTOS PROFISSIONAIS',
      filters:sihSpFilterDefinitions, tableSearchSummary:'Buscar AIH, hospital, procedimento, CNS ou profissional', tableSearchDetail:'Buscar CNS ou procedimento'
    }
  };
  const params = new URLSearchParams(location.search);
  const linkedReportId = params.get('relatorio') === 'sia-pa-belem' ? 'sia-pa-producao' : params.get('relatorio');
  let activeReport = reportConfigurations[linkedReportId] || reportConfigurations['sia-pa-producao'];
  let filterDefinitions = activeReport.filters;
  filterCategories = Object.fromEntries(Object.keys(filterDefinitions).map((type) => [type, []]));
  const linkedYear = Number(params.get('ano')) || 0;
  const linkedMonths = [...new Set(params.getAll('mes').map(Number).filter((month) => month >= 1 && month <= 12))].sort((a, b) => a - b);
  const linkedCnes = (params.get('cnes') || '').replace(/\D/g, '').slice(0, 7);
  const linkedAih = (params.get('aih') || '').replace(/\D/g, '').slice(0, 13);
  const linkedReport = Object.prototype.hasOwnProperty.call(reportConfigurations, linkedReportId) || params.get('relatorio') === 'sia-pa-belem';
  const linkedUf = String(params.get('uf') || 'PA').toUpperCase();
  const linkedMunicipality = params.get('municipio') || (params.get('relatorio') === 'sia-pa-belem' ? '150140' : '');
  const linkedFilters = { municipalityCode:linkedMunicipality };
  for (const definition of Object.values(filterDefinitions)) linkedFilters[definition.field] = params.getAll(definition.queryKey);

  function normalizeSelectedValues(value) {
    const values = Array.isArray(value) ? value : value == null || value === '' ? [] : [value];
    return [...new Set(values.map((item) => String(item).trim()).filter(Boolean))];
  }

  function summarizeSelectedNames(names) {
    if (names.length <= 3) return names.join(', ');
    return `${names.slice(0, 2).join(', ')} e mais ${names.length - 2}`;
  }

  function categoriesForFilter(type) {
    const categories = filterCategories[type] || [];
    if (type === 'professionalCbo') {
      const unique = new Map();
      for (const item of categories) {
        const code = String(item.value || '').replace(/\D/g, '');
        if (!/^\d{6}$/.test(code) || unique.has(code)) continue;
        const description = String(item.label || '').trim().replace(new RegExp(`^${code}\\s*(?:[-–—·:]\\s*)?`, 'i'), '').trim();
        unique.set(code, { value:code, label:`${code} - ${description || 'Descrição não informada'}` });
      }
      return [...unique.values()].sort((a, b) => a.label.localeCompare(b.label, 'pt-BR', { numeric:true, sensitivity:'base' }));
    }
    const municipality = municipalitySelect.value;
    if (activeReport.system !== 'sia' || type !== 'manager' || !municipality) return categories;
    const prefix = stateCodes[selectedUf()];
    const statewide = categories.filter((item) => {
      const code = String(item.value || '');
      const label = String(item.label || '').toLocaleLowerCase('pt-BR');
      return code.startsWith(prefix) && (code.endsWith('0000') || code.endsWith('9999') || label.includes('gestão estadual'));
    });
    const local = categories.filter((item) => String(item.value) === municipality);
    return [...new Map([...statewide, ...local].map((item) => [item.value, item])).values()];
  }

  function filtersFromParams(searchParams) {
    const preferred = { municipalityCode:searchParams.get('municipio') || (searchParams.get('relatorio') === 'sia-pa-belem' ? '150140' : '') };
    for (const definition of Object.values(filterDefinitions)) preferred[definition.field] = searchParams.getAll(definition.queryKey);
    return preferred;
  }

  function selectedUf() { return ufSelect.value || 'PA'; }
  function selectedOptionText(select, fallback) { return select.selectedOptions?.[0]?.textContent || fallback; }
  function selectedMonths() {
    return [...monthSelect.selectedOptions].map((option) => Number(option.value)).filter((month) => month >= 1 && month <= 12).sort((a, b) => a - b);
  }
  function allowedMonths(months, year = Number(yearSelect.value), uf = selectedUf()) {
    const valid = [...new Set(months.map(Number).filter((month) => month >= 1 && month <= 12))];
    if (valid.length < 2) return valid;
    const downloaded = new Set(localMonths(year, uf));
    return valid.every((month) => downloaded.has(month)) ? valid : [valid[valid.length - 1]];
  }
  function closeMonthPicker(returnFocus = false) {
    if (!monthPickerMenu || monthPickerMenu.hidden) return;
    monthPickerMenu.hidden = true;
    monthPickerTrigger.setAttribute('aria-expanded', 'false');
    if (returnFocus) monthPickerTrigger.focus();
  }
  function updateMonthPicker() {
    if (!monthPickerOptions) return;
    const focusedMonth = monthPickerOptions.contains(document.activeElement) ? document.activeElement.value : '';
    const options = [...monthSelect.options].filter((option) => Number(option.value) >= 1 && Number(option.value) <= 12);
    const selected = selectedMonths();
    const downloaded = new Set(localMonths(Number(yearSelect.value), selectedUf()));
    const disabled = monthSelect.disabled || options.length === 0;
    monthPickerTrigger.disabled = disabled;
    if (!options.length) monthPickerTriggerText.textContent = monthSelect.options[0]?.textContent || 'Nenhuma competência disponível';
    else if (monthSelect.disabled) monthPickerTriggerText.textContent = 'Consultando DATASUS…';
    else if (!selected.length) monthPickerTriggerText.textContent = 'Selecione as competências';
    else if (selected.length === 1) monthPickerTriggerText.textContent = `${monthNames[selected[0] - 1]} de ${yearSelect.value || ''}`.trim();
    else monthPickerTriggerText.textContent = `${selected.length} competências selecionadas`;

    monthPickerCount.textContent = selected.length > 1 ? `${selected.length} competências da biblioteca` : selected.length ? (downloaded.has(selected[0]) ? '1 competência na biblioteca' : '1 competência · busca ao abrir') : 'Nenhuma competência selecionada';
    monthPickerOptions.replaceChildren();
    for (const option of options) {
      const month = Number(option.value);
      const label = document.createElement('label');
      label.className = 'setup-competency-option';
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.value = String(month);
      checkbox.checked = option.selected;
      checkbox.disabled = disabled;
      if (option.selected) label.classList.add('is-selected');
      const text = document.createElement('span');
      text.textContent = monthNames[month - 1];
      label.append(checkbox, text);
      if (downloaded.has(month)) {
        const localBadge = document.createElement('small');
        localBadge.textContent = 'Local';
        label.append(localBadge);
      }
      monthPickerOptions.append(label);
    }
    if (focusedMonth) monthPickerOptions.querySelector(`input[value="${focusedMonth}"]`)?.focus({ preventScroll:true });
    if (disabled) closeMonthPicker();
  }
  function setSelectedMonths(months) {
    const selected = new Set(allowedMonths(months));
    for (const option of monthSelect.options) option.selected = selected.has(Number(option.value));
    updateMonthPicker();
    monthSelect.dispatchEvent(new Event('change', { bubbles:true }));
  }
  function formatCompetencies(months, year) {
    const valid = [...new Set((months || []).map(Number).filter((month) => month >= 1 && month <= 12))].sort((a, b) => a - b);
    if (valid.length === 12) return `Ano de ${year}`;
    if (valid.length === 1) return `${monthNames[valid[0] - 1]} de ${year}`;
    if (!valid.length) return String(year);
    const names = valid.map((month) => monthNames[month - 1]);
    const joined = names.length === 2 ? names.join(' e ') : `${names.slice(0, -1).join(', ')} e ${names.at(-1)}`;
    return `${joined} de ${year}`;
  }

  function activateReport(reportId) {
    const next = reportConfigurations[reportId];
    if (!next) return false;
    const changed = activeReport.id !== next.id;
    activeReport = next;
    filterDefinitions = activeReport.filters;
    if (changed) {
      activeFilterTypes = [];
      filterCategories = Object.fromEntries(Object.keys(filterDefinitions).map((type) => [type, []]));
      reportControlsReady = false;
      results.clear();
    }
    $('reportWorkspaceTitle').textContent = activeReport.workspaceTitle;
    $('reportSetupTitle').textContent = activeReport.setupTitle;
    $('reportSetupDescription').textContent = activeReport.setupDescription;
    $('reportEmptyMessage').textContent = activeReport.emptyMessage;
    const municipalityLabel = $('reportMunicipalityLabel');
    if (municipalityLabel) {
      const optional = document.createElement('small');
      optional.textContent = 'opcional';
      municipalityLabel.replaceChildren(document.createTextNode(`${activeReport.municipalityLabel} `), optional);
    }
    $('predefinedIntroLabel').textContent = activeReport.introLabel;
    $('predefinedIntroTitle').textContent = activeReport.introTitle;
    $('predefinedIntroDescription').textContent = activeReport.introDescription;
    const tag = document.querySelector('.top-tag b');
    if (tag) tag.textContent = activeReport.systemLabel;
    const sidebarSource = document.querySelector('.sidebar-foot strong');
    if (sidebarSource) sidebarSource.textContent = activeReport.systemLabel;
    const methodNote = $('reportMethodNote');
    if (methodNote) {
      const strong = document.createElement('strong');
      strong.textContent = activeReport.methodTitle;
      methodNote.replaceChildren(strong, document.createTextNode(activeReport.methodText));
    }
    const filterNote = $('reportFilterNote');
    if (filterNote) filterNote.textContent = activeReport.filterNote;
    return true;
  }
  function selectedFilters() {
    const filters = { uf:selectedUf(), municipalityCode:municipalitySelect.value || '', municipalityName:municipalitySelect.value ? selectedOptionText(municipalitySelect, '') : '' };
    for (const definition of Object.values(filterDefinitions)) {
      filters[definition.field] = [];
      filters[definition.nameField] = [];
    }
    for (const row of addedFilterRows.querySelectorAll('[data-filter-type]')) {
      const type = row.dataset.filterType;
      const definition = filterDefinitions[type];
      const select = row.querySelector('select');
      if (definition && select) {
        filters[definition.field] = [...select.selectedOptions].map((option) => option.value).filter(Boolean);
        filters[definition.nameField] = [...select.selectedOptions].filter((option) => option.value).map((option) => option.textContent || '');
      }
    }
    return filters;
  }

  async function loadReportDefaults(reportId = activeReport.id) {
    if (reportDefaults.has(reportId)) return reportDefaults.get(reportId);
    if (reportDefaultRequests.has(reportId)) return reportDefaultRequests.get(reportId);
    const request = api({ action:'report_defaults_get', report:reportId }).then((data) => {
      const defaults = data.defaults && typeof data.defaults === 'object' ? data.defaults : {};
      reportDefaults.set(reportId, defaults);
      return defaults;
    }).catch(() => {
      const defaults = {};
      reportDefaults.set(reportId, defaults);
      return defaults;
    }).finally(() => reportDefaultRequests.delete(reportId));
    reportDefaultRequests.set(reportId, request);
    return request;
  }

  function setupSettings() {
    const selected = selectedFilters();
    const filters = {};
    for (const definition of Object.values(filterDefinitions)) filters[definition.field] = selected[definition.field];
    return { uf:selected.uf, municipalityCode:selected.municipalityCode, activeFilterTypes:[...activeFilterTypes], filters };
  }

  function setupPreference() {
    const saved = reportDefaults.get(activeReport.id)?.setup;
    if (!saved || typeof saved !== 'object') return null;
    const filters = {};
    for (const definition of Object.values(filterDefinitions)) filters[definition.field] = normalizeSelectedValues(saved.filters?.[definition.field]);
    return {
      uf:stateNames[saved.uf] ? saved.uf : selectedUf(),
      municipalityCode:String(saved.municipalityCode || ''),
      activeFilterTypes:(Array.isArray(saved.activeFilterTypes) ? saved.activeFilterTypes : []).filter((type) => filterDefinitions[type]),
      filters
    };
  }

  function updateSetupDefaultControls() {
    const saved = setupPreference();
    $('clearSetupDefault').hidden = !saved;
    const matches = saved && JSON.stringify(setupSettings()) === JSON.stringify(saved);
    $('saveSetupDefault').textContent = matches ? 'Padrão salvo' : saved ? 'Atualizar padrão' : 'Salvar filtros como padrão';
    if (!matches && $('setupDefaultStatus').textContent === 'Aplicado nas próximas consultas') $('setupDefaultStatus').textContent = 'Alterações ainda não salvas';
  }

  async function saveSetupDefault() {
    const button = $('saveSetupDefault');
    button.disabled = true;
    try {
      const data = await api({ action:'report_defaults_save', report:activeReport.id, scope:'setup', settings:setupSettings() });
      reportDefaults.set(activeReport.id, data.defaults || {});
      $('setupDefaultStatus').textContent = 'Aplicado nas próximas consultas';
      updateSetupDefaultControls();
    } catch (error) {
      $('setupDefaultStatus').textContent = error.message || 'Não foi possível salvar.';
    } finally { button.disabled = false; }
  }

  async function clearSetupDefault() {
    const button = $('clearSetupDefault');
    button.disabled = true;
    try {
      const data = await api({ action:'report_defaults_delete', report:activeReport.id, scope:'setup' });
      reportDefaults.set(activeReport.id, data.defaults || {});
      $('setupDefaultStatus').textContent = 'Padrão removido';
      updateSetupDefaultControls();
    } catch (error) {
      $('setupDefaultStatus').textContent = error.message || 'Não foi possível remover.';
    } finally { button.disabled = false; }
  }

  function applySetupPreference(fallbackUf = selectedUf()) {
    const saved = setupPreference();
    setUfOptions(saved?.uf || fallbackUf);
    activeFilterTypes = saved?.activeFilterTypes || [];
    return saved ? { municipalityCode:saved.municipalityCode, ...saved.filters } : (activeReport.defaultMunicipalityCode ? { municipalityCode:activeReport.defaultMunicipalityCode } : {});
  }

  function updateScopeDescription() {
    const filters = selectedFilters();
    const months = selectedMonths();
    const year = Number(yearSelect.value);
    const parts = [months.length ? formatCompetencies(months, year) : '', stateNames[filters.uf] || filters.uf].filter(Boolean);
    if (filters.municipalityCode) parts.push(filters.municipalityName);
    const chosenFilters = Object.values(filterDefinitions).filter((definition) => filters[definition.field].length).map((definition) => `${definition.label}: ${summarizeSelectedNames(filters[definition.nameField])}`);
    parts.push(...chosenFilters);
    $('reportScopeDescription').textContent = `${parts.join(' · ')}${filters.municipalityCode || chosenFilters.length ? '' : ' · sem filtros adicionais'}`;
    updateSetupDefaultControls();
  }

  function setUfOptions(preferred = 'PA') {
    ufSelect.replaceChildren();
    for (const [uf, name] of Object.entries(stateNames).sort((a, b) => a[1].localeCompare(b[1], 'pt-BR'))) {
      ufSelect.add(new Option(`${name} · ${uf}`, uf));
    }
    ufSelect.value = Object.prototype.hasOwnProperty.call(stateNames, preferred) ? preferred : 'PA';
  }

  function setPageView(view, updateUrl = false) {
    const showReport = view === 'report';
    catalogPanel.hidden = showReport;
    workspacePanel.hidden = !showReport;
    $('predefinedMain').classList.toggle('is-report-view', showReport);
    $('predefinedIntroLabel').textContent = showReport ? activeReport.introLabel : 'RELATÓRIOS PRÉ-DEFINIDOS';
    $('predefinedIntroTitle').textContent = showReport ? activeReport.introTitle : 'Tabulações prontas para consultar.';
    $('predefinedIntroDescription').textContent = showReport ? activeReport.introDescription : 'Escolha um relatório. Cada tabulação terá seu próprio recorte e filtros.';
    if (updateUrl) {
      const next = new URL(location.href);
      if (showReport) {
        next.search = '';
        next.searchParams.set('relatorio', activeReport.id);
        next.searchParams.set('uf', selectedUf());
      } else next.search = '';
      history.pushState({ report: showReport ? activeReport.id : null }, '', next);
    }
    window.scrollTo({ top: 0, behavior: 'instant' });
  }

  async function prepareReportControls(preferred = {}) {
    setAvailability('Preparando as opções desta tabulação…', 'loading');
    if (!reportControlsReady) {
      try {
        const catalog = await api({ action: 'catalog' });
        addLocalFiles(catalog.files);
      } catch (_) {
        // Remote lookup can still work if the local catalog is not available yet.
      }
      reportControlsReady = true;
    }
    await Promise.all([
      refreshCompetencies(Number(yearSelect.value), selectedMonths().length ? selectedMonths() : linkedMonths, selectedUf()),
      loadOptionalFilters(selectedUf(), preferred)
    ]);
    updateScopeDescription();
  }

  async function openReportSetup(preferred = selectedFilters()) {
    if (!setupDialog.open) setupDialog.showModal();
    $('setupDefaultStatus').textContent = '';
    $('saveSetupDefault').disabled = true;
    try { await prepareReportControls(preferred); }
    finally {
      $('saveSetupDefault').disabled = false;
      updateSetupDefaultControls();
    }
  }

  function returnToCatalog(updateUrl = true) {
    if (setupDialog.open) setupDialog.close();
    setPageView('catalog', updateUrl);
  }

  async function api(payload) {
    let response;
    try {
      response = await fetch('api.php', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-SPPtab-CSRF': csrf },
        body: JSON.stringify(payload)
      });
    } catch (_) {
      throw new Error('Não foi possível falar com o SPPtab local. Confira se o aplicativo continua aberto.');
    }
    const body = await response.text();
    let data;
    try { data = JSON.parse(body); }
    catch (_) { throw new Error(body.trim() || 'O serviço local respondeu sem dados. Atualize a página e tente novamente.'); }
    if (!response.ok || !data?.ok) throw new Error(data?.error || 'Não foi possível concluir a solicitação.');
    return data;
  }

  function setAvailability(text, tone = '') {
    availability.replaceChildren();
    availability.className = `report-availability${tone ? ` is-${tone}` : ''}`;
    if (tone === 'loading') {
      const mark = document.createElement('span');
      mark.className = 'report-availability-mark tile-motif';
      mark.setAttribute('aria-hidden', 'true');
      for (let i = 0; i < 5; i += 1) mark.append(document.createElement('i'));
      const label = document.createElement('span');
      label.textContent = text;
      availability.append(mark, label);
    } else availability.textContent = text;
  }

  function showNotice(text, tone = 'info') {
    notice.hidden = !text;
    notice.className = `report-notice${text ? ` is-${tone}` : ''}`;
    notice.textContent = text || '';
  }

  function showReportFailure(error) {
    const message = String(error?.message || error || 'O relatório não foi concluído. Confira a conexão e tente novamente.');
    setLoader(false);
    resultPanel.hidden = true;
    empty.hidden = false;
    $('reportEmpty').querySelector('strong').textContent = 'Não foi possível gerar o relatório';
    $('reportEmptyMessage').textContent = `Confira a conexão com o DATASUS e tente novamente. ${activeReport.emptyMessage}`;
    showNotice(message, 'error');
  }

  function setLoader(visible, title = '', description = '', percent = null, indeterminate = false) {
    loader.hidden = !visible;
    loader.setAttribute('aria-busy', visible ? 'true' : 'false');
    if (!visible) {
      downloadQueue.hidden = true;
      return;
    }
    stage.textContent = title;
    detail.textContent = description;
    const hasProgress = percent !== null && Number.isFinite(Number(percent));
    progress.hidden = !hasProgress && !indeterminate;
    progress.classList.toggle('is-indeterminate', Boolean(indeterminate));
    progressLabel.hidden = !hasProgress;
    if (hasProgress) {
      const value = Math.max(0, Math.min(100, Number(percent)));
      progressFill.style.width = `${value}%`;
      progressLabel.textContent = `${Math.round(value)}%`;
      progress.setAttribute('role', 'progressbar');
      progress.setAttribute('aria-valuenow', String(Math.round(value)));
    } else {
      progressFill.style.width = '';
      progress.removeAttribute('aria-valuenow');
    }
  }

  function downloadTaskKey(year, month, kind) {
    return `${year}-${month}-${kind}`;
  }

  function beginDownloadQueue(year, months, view) {
    downloadTasks.clear();
    downloadFiles.replaceChildren();
    downloadQueue.hidden = months.length < 2;
    if (downloadQueue.hidden) return;
    const { kinds } = reportKindsForView(view);
    for (const month of months) {
      for (const kind of kinds) {
        const row = document.createElement('div');
        row.className = 'report-download-file';
        row.dataset.status = 'pending';
        const name = document.createElement('span');
        name.className = 'report-download-file-name';
        name.textContent = `${kind} · ${monthNames[month - 1]} ${year}`;
        const state = document.createElement('span');
        state.className = 'report-download-file-state';
        state.textContent = 'Aguardando';
        row.append(name, state);
        downloadFiles.append(row);
        downloadTasks.set(downloadTaskKey(year, month, kind), { row, name, state });
      }
    }
    updateDownloadHeading();
  }

  function updateDownloadHeading() {
    if (downloadQueue.hidden) return;
    const tasks = [...downloadTasks.values()];
    const finished = tasks.filter(({ row }) => ['ready', 'unavailable', 'error'].includes(row.dataset.status)).length;
    downloadHeading.textContent = `Arquivos conferidos: ${finished} de ${tasks.length} · transferência individual`;
  }

  function updateDownloadTask(year, month, kind, status, fileName = '') {
    const task = downloadTasks.get(downloadTaskKey(year, month, kind));
    if (!task) return;
    const labels = { pending:'Aguardando', checking:'Localizando', downloading:'Baixando', ready:fileName ? 'Baixado' : 'Na base', unavailable:'Não publicado', error:'Falha' };
    task.row.dataset.status = status;
    task.state.textContent = labels[status] || status;
    if (fileName) task.name.title = fileName;
    updateDownloadHeading();
  }

  function localFor(year, month, uf = selectedUf()) {
    const wanted = `${activeReport.kind}${uf}${String(year).slice(-2)}${String(month).padStart(2, '0')}.dbc`.toUpperCase();
    return localForKind(year, month, uf, activeReport.kind, wanted);
  }

  function localForKind(year, month, uf, kind, wantedName = '') {
    const wanted = wantedName || `${kind}${uf}${String(year).slice(-2)}${String(month).padStart(2, '0')}.dbc`.toUpperCase();
    return [...localFiles.values()].find((file) => file.name?.toUpperCase() === wanted && file.system === activeReport.systemCode && file.kind === kind && String(file.uf || '').toUpperCase() === uf);
  }

  function addLocalFiles(files) {
    for (const file of files || []) {
      const system = String(file?.system || '').toUpperCase();
      const kind = String(file?.kind || '').toUpperCase();
      if (file?.path && file.name && Object.values(reportConfigurations).some((report) => report.systemCode === system && [report.kind, ...(report.requiredKinds || []), ...(report.optionalKinds || []), ...Object.values(report.kindsByView || {}).flat()].includes(kind)) && stateNames[String(file.uf || '').toUpperCase()]) localFiles.set(file.path, { ...file, system, kind, uf: String(file.uf).toUpperCase() });
    }
  }

  function setMonthOptions(months, preferred = []) {
    const valid = [...new Set(months.map(Number).filter((month) => month >= 1 && month <= 12))].sort((a, b) => a - b);
    monthSelect.replaceChildren();
    if (!valid.length) {
      monthSelect.add(new Option('Nenhuma competência disponível', ''));
      monthSelect.disabled = true;
      openButton.disabled = true;
      updateMonthPicker();
      return false;
    }
    const requested = allowedMonths((Array.isArray(preferred) ? preferred : [preferred]).map(Number).filter((month) => valid.includes(month)), Number(yearSelect.value), selectedUf());
    const chosen = requested.length ? requested : [valid[valid.length - 1]];
    for (const month of valid) {
      const option = new Option(monthNames[month - 1], String(month));
      option.selected = chosen.includes(month);
      monthSelect.add(option);
    }
    monthSelect.disabled = false;
    openButton.disabled = selectedMonths().length === 0;
    updateMonthPicker();
    return true;
  }

  function localMonths(year, uf = selectedUf()) {
    const kinds = activeReport.requiredKinds || [activeReport.kind];
    const monthsByKind = kinds.map((kind) => new Set([...localFiles.values()].filter((file) => file.system === activeReport.systemCode && file.kind === kind && Number(file.year) === Number(year) && String(file.uf || '').toUpperCase() === uf).map((file) => Number(file.month))));
    return [...(monthsByKind[0] || new Set())].filter((month) => monthsByKind.every((months) => months.has(month)));
  }

  async function refreshCompetencies(year, preferred = [], uf = selectedUf()) {
    const requestId = ++competencyRequest;
    const cachedMonths = localMonths(year, uf);
    const hasLocal = setMonthOptions(cachedMonths, preferred);
    if (hasLocal) setAvailability(`${cachedMonths.length} competência(s) de ${uf} já salva(s) neste computador.`, 'good');
    else {
      monthSelect.disabled = true;
      monthSelect.replaceChildren(new Option('Consultando DATASUS…', ''));
      updateMonthPicker();
      openButton.disabled = true;
      setAvailability('Consultando competências no DATASUS.', 'loading');
    }

    try {
      const response = await api({ action: 'competencies', system: activeReport.system, year: Number(year), uf });
      if (requestId !== competencyRequest) return;
      const requiredKinds = activeReport.requiredKinds || [activeReport.kind];
      const availableFiles = (response.files || []).filter((file) => String(file.uf || '').toUpperCase() === uf);
      const monthsByKind = requiredKinds.map((kind) => new Set(availableFiles.filter((file) => file.kind === kind).map((file) => Number(file.month))));
      const reportMonths = [...(monthsByKind[0] || new Set())].filter((month) => monthsByKind.every((months) => months.has(month)));
      const merged = [...new Set([...cachedMonths, ...reportMonths])];
      const selected = (Array.isArray(preferred) ? preferred : [preferred]).map(Number).filter((month) => merged.includes(month));
      setMonthOptions(merged, selected);
      const localCount = new Set(cachedMonths).size;
      setAvailability(`${merged.length} competência(s) de ${uf} encontrada(s) · ${localCount} na biblioteca local. Vários meses apenas com arquivos locais.`, 'good');
    } catch (error) {
      if (requestId !== competencyRequest) return;
      if (hasLocal) setAvailability(`${cachedMonths.length} competência(s) de ${uf} na biblioteca local · DATASUS indisponível no momento.`, '');
      else {
        setMonthOptions([], 0);
        setAvailability(error.message, 'error');
      }
    }
  }

  function resetSelect(select, defaultLabel) {
    select.replaceChildren(new Option(defaultLabel, ''));
    select.value = '';
  }

  function refreshAddFilterOptions() {
    const selected = addFilterSelect.value;
    addFilterSelect.replaceChildren(new Option('Adicionar filtro opcional…', ''));
    for (const [type, definition] of Object.entries(filterDefinitions)) {
      if (!activeFilterTypes.includes(type)) addFilterSelect.add(new Option(definition.label, type));
    }
    addFilterSelect.disabled = !Object.keys(filterDefinitions).some((type) => !activeFilterTypes.includes(type));
    if ([...addFilterSelect.options].some((option) => option.value === selected)) addFilterSelect.value = selected;
    else addFilterSelect.value = '';
  }

  function renderAdditionalFilterRows(preferred = {}) {
    addedFilterRows.replaceChildren();
    for (const type of activeFilterTypes) {
      const definition = filterDefinitions[type];
      if (!definition) continue;
      const row = document.createElement('div');
      row.className = 'setup-filter-row';
      row.dataset.filterType = type;
      const title = document.createElement('strong');
      title.textContent = definition.label;
      const source = document.createElement('small');
      source.className = 'setup-filter-source';
      source.textContent = definition.sourceLabel ? `Origem: ${definition.sourceLabel}` : '';
      const label = document.createElement('label');
      label.className = 'field';
      const caption = document.createElement('span');
      caption.textContent = 'CATEGORIAS · CTRL/⌘ + CLIQUE PARA VÁRIAS';
      const select = document.createElement('select');
      select.multiple = true;
      const categories = categoriesForFilter(type);
      select.size = Math.min(6, Math.max(2, categories.length));
      select.setAttribute('aria-label', `${definition.label}. Segure Ctrl no Windows ou Command no Mac para selecionar várias categorias.`);
      select.setAttribute('aria-describedby', 'reportFilterNote');
      const preferredValues = normalizeSelectedValues(preferred[definition.field]);
      if (type === 'professionalCbo') {
        const search = document.createElement('input');
        search.className = 'setup-filter-search';
        search.type = 'search';
        search.placeholder = 'Buscar pelo código ou nome do CBO…';
        search.autocomplete = 'off';
        search.setAttribute('aria-label', 'Buscar CBO pelo código ou nome');
        const selectedValues = new Set(preferredValues);
        const renderCboOptions = () => {
          const query = search.value.trim().normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR');
          const matches = categories.filter((item) => `${item.value} ${item.label}`.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR').includes(query));
          const matchValues = new Set(matches.map((item) => item.value));
          const visible = [...matches, ...categories.filter((item) => selectedValues.has(item.value) && !matchValues.has(item.value))];
          select.replaceChildren(...visible.map((item) => new Option(item.label, item.value, false, selectedValues.has(item.value))));
          select.size = Math.min(6, Math.max(2, visible.length));
        };
        renderCboOptions();
        search.addEventListener('input', renderCboOptions);
        select.addEventListener('change', () => {
          selectedValues.clear();
          for (const option of select.selectedOptions) selectedValues.add(option.value);
          updateScopeDescription();
        });
        label.append(caption, search, select);
      } else {
        for (const item of categories) select.add(new Option(item.label, item.value));
        for (const option of select.options) option.selected = preferredValues.includes(option.value);
        select.addEventListener('change', updateScopeDescription);
        label.append(caption, select);
      }
      const remove = document.createElement('button');
      remove.className = 'setup-filter-remove';
      remove.type = 'button';
      remove.dataset.removeFilter = type;
      remove.textContent = 'Remover';
      row.append(title, source, label, remove);
      addedFilterRows.append(row);
    }
    refreshAddFilterOptions();
    updateScopeDescription();
  }

  async function loadOptionalFilters(uf, preferred = {}) {
    const requestId = ++filterRequest;
    setAvailability('Carregando filtros da definição oficial…', 'loading');
    resetSelect(municipalitySelect, 'Todos os municípios');
    const preferredMunicipality = String(preferred.municipalityCode || '');
    for (const [type, definition] of Object.entries(filterDefinitions)) {
      if (normalizeSelectedValues(preferred[definition.field]).length && !activeFilterTypes.includes(type)) activeFilterTypes.push(type);
    }
    for (const type of Object.keys(filterDefinitions)) filterCategories[type] = [];
    refreshAddFilterOptions();
    municipalitySelect.disabled = false;
    const municipalityTask = api({ action: 'municipalities', uf }).then((data) => {
      if (requestId !== filterRequest) return;
      const options = (data.municipalities || []).map((item) => ({ value: String(item.code || ''), label: String(item.name || '') })).filter((item) => /^\d{6}$/.test(item.value) && item.value.startsWith(stateCodes[uf]) && item.label);
      for (const item of options) municipalitySelect.add(new Option(item.label, item.value));
      municipalitySelect.value = [...municipalitySelect.options].some((option) => option.value === preferredMunicipality) ? preferredMunicipality : '';
    }).catch(() => {
      if (requestId !== filterRequest) return;
      municipalitySelect.title = 'A lista de municípios não foi carregada. O relatório continua disponível para toda a UF.';
    });
    const categoryTask = api({ action: 'predefined_filter_options', report:activeReport.id, uf }).then((data) => {
      if (requestId !== filterRequest) return;
      for (const [type, definition] of Object.entries(filterDefinitions)) filterCategories[type] = data[definition.responseKey] || [];
    }).catch(() => {
      if (requestId !== filterRequest) return;
      for (const type of Object.keys(filterDefinitions)) filterCategories[type] = [];
    });
    await Promise.all([municipalityTask, categoryTask]);
    if (requestId === filterRequest) renderAdditionalFilterRows(preferred);
  }

  function formatNumber(value, decimals = 0) {
    const number = Number(value || 0);
    return number.toLocaleString('pt-BR', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  }

  function scaledInteger(value, decimals) {
    const text = String(value ?? '0').trim();
    const match = text.match(/^([+-]?)(\d*)(?:\.(\d*))?$/);
    if (!match) return 0n;
    const places = Math.max(0, Number(decimals) || 0);
    const whole = match[2] || '0';
    const fraction = (match[3] || '').slice(0, places).padEnd(places, '0');
    const unsigned = BigInt(`${whole}${fraction}` || '0');
    return match[1] === '-' ? -unsigned : unsigned;
  }

  function formatScaled(value, decimals) {
    const places = Math.max(0, Number(decimals) || 0);
    const integer = typeof value === 'bigint' ? value : BigInt(value || 0);
    const negative = integer < 0n;
    const absolute = negative ? -integer : integer;
    const scale = 10n ** BigInt(places);
    const whole = places ? absolute / scale : absolute;
    const fraction = places ? String(absolute % scale).padStart(places, '0') : '';
    const grouped = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 }).format(whole);
    return `${negative ? '-' : ''}${grouped}${places ? `,${fraction}` : ''}`;
  }

  function buildCell(tag, text, className = '') {
    const cell = document.createElement(tag);
    if (className) cell.className = className;
    cell.textContent = text;
    return cell;
  }

  function tableColumns() {
    if (!activeResult) return [];
    const competenceColumn = { id:'competence', label:'Competência', field:'competence', type:'text', sortField:'competence', filterable:true, sortable:true };
    if (activeReport.tableMode === 'flat' || activeReport.tableMode === 'occupancy') {
      const columns = (activeResult.columns || []).map((column) => ({ ...column, filterable:column.kind !== 'action', sortable:column.kind !== 'action' }));
      const actionIndex = columns.findIndex((column) => column.kind === 'action');
      columns.splice(actionIndex < 0 ? columns.length : actionIndex, 0, competenceColumn);
      return columns;
    }
    const summaryView = activeView === 'summary';
    let dimensions = summaryView ? [] : [...(activeResult.detailDimensions || [{ id:'complexity', label:'Complexidade' }])];
    if (activeReport.id === 'sia-pa-producao' && !summaryView) {
      const extraDimensions = dimensions.filter((dimension) => !['complexity','financing'].includes(dimension.id));
      dimensions = [
        { id:'complexity', label:'Complexidade' },
        { id:'financing', label:'Financiamento (MAC/FAEC)' },
        ...extraDimensions
      ];
    }
    const columns = [{
      id:'primary', label:summaryView ? (activeResult.dimensionLabel || 'ESTABELECIMENTO') : (activeResult.dimensionLabel || 'PROCEDIMENTO · SIGTAP'),
      kind:'primary', primaryField:'label', secondaryField:'code', secondaryPrefix:summaryView ? 'CNES ' : '',
      type:'text', sortField:'label', filterFields:['label','code'], sticky:true, filterable:true, sortable:true
    }];
    for (const dimension of dimensions) columns.push({ id:`dimension:${dimension.id}`, label:dimension.label, field:dimension.id, type:'text', filterable:true, sortable:true });
    for (const [index, metric] of (activeResult.metrics || []).entries()) columns.push({ id:`metric:${metric.id}`, label:metric.label, metricId:metric.id, metricIndex:index, type:'number', decimals:metric.decimals, filterable:true, sortable:true });
    columns.push(competenceColumn);
    if (summaryView) columns.push({ id:'action', label:'Detalhamento', kind:'action', filterable:false, sortable:false });
    return columns;
  }

  function rawColumnValue(row, column) {
    if (column.metricId) {
      const index = column.metricIndex ?? (activeResult?.metrics || []).findIndex((item) => item.id === column.metricId);
      return row[column.metricId] ?? row.values?.[index] ?? '';
    }
    if (column.kind === 'primary') return row[column.primaryField] ?? '';
    return row[column.field] ?? '';
  }

  function columnFilterToken(row, column) {
    if (column.metricId) return String(rawColumnValue(row, column) ?? '').trim();
    const fields = column.filterFields || (column.primaryField ? [column.primaryField, column.secondaryField, column.tertiaryCodeField, column.tertiaryField] : [column.field]);
    return fields.filter(Boolean).map((field) => String(row[field] ?? '').trim()).filter(Boolean).join(' · ');
  }

  function columnDisplayValue(row, column) {
    if (column.metricId) {
      const raw = rawColumnValue(row, column);
      const formatted = formatNumber(raw, column.decimals);
      return column.type === 'currency' ? `R$ ${formatted}` : formatted;
    }
    const fields = column.filterFields || (column.primaryField ? [column.primaryField, column.secondaryField, column.tertiaryCodeField, column.tertiaryField] : [column.field]);
    const parts = fields.filter(Boolean).map((field) => String(row[field] ?? '').trim()).filter(Boolean);
    return parts.length ? parts.join(' · ') : '(Vazio)';
  }

  function tableSearchText(row, columns) {
    return columns.filter((column) => column.kind !== 'action').map((column) => columnDisplayValue(row, column)).join(' ').toLocaleLowerCase('pt-BR');
  }

  function rowsMatchingFilters(exceptColumn = '') {
    const query = $('reportSearch').value.trim().toLocaleLowerCase('pt-BR');
    const columns = tableColumns();
    return allRows.filter((row) => {
      if (query && !tableSearchText(row, columns).includes(query)) return false;
      for (const [columnId, excluded] of columnFilters) {
        if (!excluded.size || columnId === exceptColumn) continue;
        const column = columns.find((item) => item.id === columnId);
        if (column && excluded.has(columnFilterToken(row, column))) return false;
      }
      return true;
    });
  }

  function compareColumnValues(left, right, column) {
    const a = rawColumnValue(left, column);
    const b = rawColumnValue(right, column);
    if (column.type === 'number' || column.type === 'currency' || column.type === 'percent') {
      const decimals = Number(column.decimals) || 0;
      const aValue = scaledInteger(a, decimals);
      const bValue = scaledInteger(b, decimals);
      return aValue < bValue ? -1 : aValue > bValue ? 1 : 0;
    }
    const field = column.sortField;
    const aValue = String(field ? left[field] ?? '' : a ?? '').trim();
    const bValue = String(field ? right[field] ?? '' : b ?? '').trim();
    return aValue.localeCompare(bValue, 'pt-BR', { numeric:true, sensitivity:'base' });
  }

  function visibleRows() {
    let rows = rowsMatchingFilters();
    if (sortState) {
      const column = tableColumns().find((item) => item.id === sortState.columnId);
      if (column) rows = [...rows].sort((a, b) => compareColumnValues(a, b, column) * (sortState.direction === 'desc' ? -1 : 1));
    }
    return rows;
  }

  function totalsFor(rows, metrics) {
    return metrics.map((metric, index) => rows.reduce((sum, row) => sum + scaledInteger(row[metric.id] ?? row.values?.[index], metric.decimals), 0n));
  }

  function renderKpis(rows, totals, metrics) {
    const box = $('reportKpis');
    box.replaceChildren();
    const qtyIndex = metrics.findIndex((metric) => metric.id === activeReport.countMetric);
    const valueIndex = metrics.findIndex((metric) => metric.id === activeReport.valueMetric);
    let cards;
    if (activeResult.kpis) {
      cards = activeResult.kpis.map((item) => [item.label, item.value]);
    } else if (activeReport.tableMode === 'flat') {
      const aihCount = new Set(rows.map((row) => String(row.aih || '')).filter(Boolean)).size;
      cards = [
        ['AIHs', formatNumber(aihCount)],
        [activeReport.countLabel, qtyIndex >= 0 ? formatScaled(totals[qtyIndex], metrics[qtyIndex].decimals) : '—'],
        [activeReport.valueLabel, valueIndex >= 0 ? `R$ ${formatScaled(totals[valueIndex], metrics[valueIndex].decimals)}` : '—']
      ];
    } else {
      cards = [
        [activeView === 'summary' ? 'ESTABELECIMENTOS' : activeReport.detailCountLabel, formatNumber(rows.length)],
        [activeReport.countLabel, qtyIndex >= 0 ? formatScaled(totals[qtyIndex], metrics[qtyIndex].decimals) : '—'],
        [activeReport.valueLabel, valueIndex >= 0 ? `R$ ${formatScaled(totals[valueIndex], metrics[valueIndex].decimals)}` : '—']
      ];
    }
    for (const [label, value] of cards) {
      const card = document.createElement('div'); card.className = 'report-kpi';
      const formatted = activeResult.kpis && value && typeof value === 'object'
        ? (value.text || `${value.prefix || ''}${formatNumber(value.value, value.decimals || 0)}${value.suffix || ''}`)
        : value;
      card.append(buildCell('span', label), buildCell('strong', formatted)); box.append(card);
    }
  }

  function renderTableCell(row, column, firstColumn = false) {
    if (column.kind === 'action') {
      const action = document.createElement('td'); action.className = 'report-action-cell';
      const button = document.createElement('button'); button.type = 'button'; button.className = 'report-detail-button';
      button.dataset.month = String(row._competenceMonth || activeMonth || '');
      button.dataset.year = String(row._competenceYear || activeYear || '');
      if (column.actionType === 'services') { button.dataset.aih = row.aih; button.dataset.cnes = row.cnes || activeCnes; button.dataset.action = 'services'; button.textContent = 'Serviços →'; }
      else { button.dataset.cnes = row.code || row.cnes; button.dataset.action = 'detail'; button.textContent = column.actionLabel || 'Detalhar →'; }
      action.append(button); return action;
    }
    const cell = document.createElement('td');
    if (column.id === 'dimension:rejectionReason' || column.field === 'rejectionReason') cell.classList.add('report-rejection-reason-column');
    if (column.id === 'dimension:complexity') cell.classList.add('report-complexity-column');
    if (column.id === 'dimension:financing') cell.classList.add('report-financing-column');
    if (column.id === 'specialty') cell.classList.add('report-bed-specialty-column');
    if (column.id === 'procedure' && activeReport.tableMode === 'occupancy') cell.classList.add('report-bed-procedure-column');
    if (firstColumn || column.sticky) cell.classList.add('primary-cell');
    if (column.metricId) {
      const formatted = formatNumber(rawColumnValue(row, column), column.decimals);
      cell.textContent = column.type === 'currency' ? `R$ ${formatted}` : formatted;
      return cell;
    }
    if (column.type === 'number' || column.type === 'currency' || column.type === 'percent') {
      const raw = rawColumnValue(row, column);
      if (raw === '' || raw == null) { cell.textContent = 'Não disponível'; return cell; }
      const formatted = formatNumber(raw, column.decimals);
      const value = column.type === 'currency' ? `R$ ${formatted}` : column.type === 'percent' ? `${formatted}%` : formatted;
      if (column.secondaryField && row[column.secondaryField] != null) {
        const stack = document.createElement('span'); stack.className = 'report-cell-stack';
        stack.append(buildCell('span', value, 'report-primary-label'));
        stack.append(buildCell('small', `${column.secondaryPrefix || ''}${formatNumber(row[column.secondaryField], 0)}`, 'report-primary-code'));
        cell.append(stack);
      } else cell.textContent = value;
      return cell;
    }
    if (column.kind === 'primary') {
      cell.append(buildCell('span', row[column.primaryField] || 'Descrição não disponível', 'report-primary-label'));
      const secondary = row[column.secondaryField] || '';
      const label = column.secondaryPrefix ? `${column.secondaryPrefix}${secondary}` : secondary;
      if (label && label !== row[column.primaryField]) cell.append(buildCell('span', label, 'report-primary-code'));
      return cell;
    }
    if (column.primaryField) {
      const stack = document.createElement('span'); stack.className = 'report-cell-stack';
      const main = String(row[column.primaryField] || '').trim();
      stack.append(buildCell('span', main || 'Não informado', 'report-primary-label'));
      if (column.secondaryField && row[column.secondaryField]) stack.append(buildCell('small', `${column.secondaryPrefix || ''}${row[column.secondaryField]}`, 'report-primary-code'));
      if (column.tertiaryCodeField || column.tertiaryField) {
        const code = String(column.tertiaryCodeField ? row[column.tertiaryCodeField] || '' : '').trim();
        const label = String(column.tertiaryField ? row[column.tertiaryField] || '' : '').trim();
        const third = [code ? `${column.tertiaryPrefix || ''}${code}` : '', label].filter(Boolean).join(' · ');
        if (third) stack.append(buildCell('small', third, 'report-primary-code'));
      }
      cell.append(stack);
      return cell;
    }
    if (column.field === 'rejectionReason') {
      const values = Array.isArray(row.rejectionReasonItems) && row.rejectionReasonItems.length
        ? row.rejectionReasonItems
        : String(row.rejectionReason || 'Motivo não disponível no SIH/ER').split(' · ');
      const list = document.createElement('ul'); list.className = 'report-rejection-reason-list';
      for (const value of values) list.append(buildCell('li', value));
      cell.append(list);
      return cell;
    }
    cell.textContent = String(row[column.field] || 'Não informado');
    return cell;
  }

  function renderHeader(columns) {
    const header = $('reportHeader'); header.replaceChildren();
    for (const column of columns) {
      const th = document.createElement('th');
      if (column.id === 'dimension:rejectionReason' || column.field === 'rejectionReason') th.classList.add('report-rejection-reason-column');
      if (column.id === 'dimension:complexity') th.classList.add('report-complexity-column');
      if (column.id === 'dimension:financing') th.classList.add('report-financing-column');
      if (column.id === 'specialty') th.classList.add('report-bed-specialty-column');
      if (column.id === 'procedure' && activeReport.tableMode === 'occupancy') th.classList.add('report-bed-procedure-column');
      if (column.sticky || columns[0] === column) th.classList.add('primary-cell');
      if (column.kind === 'action') { th.classList.add('report-action-cell'); th.textContent = column.label; header.append(th); continue; }
      const wrap = document.createElement('span'); wrap.className = 'report-column-head';
      const label = buildCell('span', column.label);
      if (sortState?.columnId === column.id) label.append(document.createTextNode(sortState.direction === 'desc' ? ' ↓' : ' ↑'));
      wrap.append(label);
      const button = document.createElement('button'); button.type = 'button'; button.className = `report-column-menu-trigger${columnFilters.has(column.id) ? ' is-filtered' : ''}`;
      button.dataset.columnFilter = column.id; button.setAttribute('aria-label', `Filtrar e ordenar ${column.label}`); button.title = 'Filtrar e ordenar'; button.textContent = columnFilters.has(column.id) ? '▼•' : '▼';
      wrap.append(button); th.append(wrap); header.append(th);
    }
  }

  function renderTable() {
    if (!activeResult) return;
    resultPanel.classList.toggle('is-flat-report', activeReport.tableMode === 'flat');
    resultPanel.classList.toggle('is-bed-occupancy-report', activeReport.tableMode === 'occupancy');
    resultPanel.classList.toggle('is-sia-detail-report', activeReport.id === 'sia-pa-producao' && activeView === 'detail');
    const rows = visibleRows();
    const pageCount = Math.max(1, Math.ceil(rows.length / tablePageSize));
    tablePage = Math.min(Math.max(1, tablePage), pageCount);
    const pageRows = rows.slice((tablePage - 1) * tablePageSize, tablePage * tablePageSize);
    const metrics = activeResult.metrics || [];
    const columns = tableColumns();
    renderHeader(columns);
    const body = $('reportRows'); body.replaceChildren();
    for (const row of pageRows) {
      const tr = document.createElement('tr');
      columns.forEach((column, index) => tr.append(renderTableCell(row, column, index === 0)));
      body.append(tr);
    }
    if (!rows.length) {
      const tr = document.createElement('tr');
      tr.append(buildCell('td', 'Nenhum resultado corresponde aos filtros aplicados.', 'primary-cell'));
      const spacer = document.createElement('td'); spacer.colSpan = Math.max(1, columns.length - 1); tr.append(spacer); body.append(tr);
    }

    const totals = totalsFor(rows, metrics);
    const occupancyTotals = activeReport.tableMode === 'occupancy' ? occupancyTotalsFor(rows) : null;
    const foot = $('reportTotals'); foot.replaceChildren();
    const countLabel = rows.length < allRows.length ? `Total · ${formatNumber(rows.length)} itens visíveis` : 'Total';
    foot.append(buildCell('td', countLabel, 'primary-cell'));
    for (const column of columns.slice(1)) {
      if (column.metricId) {
        const metricIndex = metrics.findIndex((metric) => metric.id === column.metricId);
        const value = metricIndex >= 0 ? formatScaled(totals[metricIndex], metrics[metricIndex].decimals) : '';
        foot.append(buildCell('td', column.type === 'currency' && value ? `R$ ${value}` : value));
      } else if (occupancyTotals && column.totalField) {
        const raw = Object.prototype.hasOwnProperty.call(occupancyTotals, column.totalField) ? occupancyTotals[column.totalField] : (activeView !== 'summary' ? rows.reduce((total, row) => total + (Number(String(row[column.totalField] ?? '').replace(',', '.')) || 0), 0) : null);
        const formatted = raw == null ? '' : formatNumber(raw, column.decimals);
        const totalText = column.type === 'currency' && formatted ? `R$ ${formatted}` : column.type === 'percent' && formatted ? `${formatted}%` : formatted;
        foot.append(buildCell('td', totalText, column.kind === 'action' ? 'report-action-cell' : ''));
      } else foot.append(buildCell('td', '', column.kind === 'action' ? 'report-action-cell' : ''));
    }

    $('reportCount').textContent = formatNumber(rows.length);
    const itemLabel = activeReport.tableMode === 'flat' ? 'lançamentos' : activeReport.tableMode === 'occupancy' ? (activeView === 'summary' ? 'estabelecimentos' : activeView === 'detail' ? 'AIHs' : 'serviços profissionais') : activeView === 'summary' ? 'estabelecimentos' : (activeReport.system === 'sih' ? 'combinações de procedimento' : 'procedimentos');
    $('reportTableHint').textContent = `${formatNumber(rows.length)} de ${formatNumber(allRows.length)} ${itemLabel} · página ${formatNumber(tablePage)} de ${formatNumber(pageCount)} · filtre ou ordene pelos cabeçalhos`;
    renderTablePagination(rows.length, pageCount);
    const locationParts = [activeResult.municipality || 'Todos os municípios', activeResult.state || stateNames[activeResult.uf] || activeResult.uf];
    const appliedFilters = Array.isArray(activeResult.filters) ? activeResult.filters : [
      ...(activeResult.managerCode ? [{ label:'Gestor da produção', value:activeResult.manager }] : []),
      ...(activeResult.legalNatureCode ? [{ label:'Natureza jurídica', value:activeResult.legalNature }] : [])
    ];
    for (const filter of appliedFilters) if (filter?.label && filter?.value) locationParts.push(`${filter.label}: ${filter.value}`);
    const fileSummary = activeMonths.length > 1 ? `${formatNumber(activeMonths.length)} competências consultadas` : activeResult.file || '';
    $('reportSubtitle').textContent = `${formatCompetencies(activeMonths, activeYear)} · ${locationParts.join(' · ')} · ${fileSummary}`;
    $('reportTitle').textContent = activeReport.tableMode === 'flat' || activeView === 'summary' ? activeReport.summaryTitle : activeView === 'services' ? `Serviços profissionais · AIH ${activeAih}` : `${activeReport.detailTitlePrefix} · ${activeResult.establishmentName || `CNES ${activeCnes}`}`;
    $('reportSearch').placeholder = activeView === 'summary' ? activeReport.tableSearchSummary : activeView === 'services' ? 'Buscar profissional, procedimento ou CNS' : activeReport.tableSearchDetail;
    renderKpis(rows, totals, metrics);
    const notes = $('reportNotes'); notes.replaceChildren();
    for (const note of activeResult.notes || []) {
      const line = document.createElement('p'); line.textContent = note; notes.append(line);
    }
    $('backToSummary').hidden = activeReport.tableMode === 'flat' || activeView === 'summary';
    $('backToSummary').textContent = activeView === 'services' ? '← AIH' : '← Estabelecimentos';
    resultPanel.hidden = false;
    empty.hidden = true;
    updateTableDefaultControls();
  }

  function occupancyTotalsFor(rows) {
    const sum = (field) => rows.reduce((total, row) => total + (Number(String(row[field] ?? '').replace(',', '.')) || 0), 0);
    if ((activeResult?.months || []).length > 1) {
      const capacityByProvider = new Map();
      for (const row of rows) {
        const code = String(row.code || row.cnes || row.label || '');
        const previous = capacityByProvider.get(code);
        if (!previous || Number(row._competenceMonth) > Number(previous._competenceMonth)) capacityByProvider.set(code, row);
      }
      const capacityRows = [...capacityByProvider.values()];
      const bedsKnown = capacityRows.every((row) => row.bedsSus != null && row.bedsSus !== '');
      const beds = bedsKnown ? capacityRows.reduce((total, row) => total + (Number(row.bedsSus) || 0), 0) : null;
      const actualDays = sum('dailyCount');
      const visibleMonths = [...new Set(rows.map((row) => Number(row._competenceMonth)).filter((month) => month >= 1 && month <= 12))];
      const calendarDays = visibleMonths.reduce((total, month) => total + new Date(activeYear, month, 0).getDate(), 0);
      const bedDays = (beds || 0) * calendarDays;
      const rejected = sum('rejectedCount');
      const processed = sum('aihCount');
      const rowsByProviderMonth = new Map(rows.map((row) => [`${row._competenceMonth}:${row.code || row.cnes || row.label}`, row]));
      const monthlyBalances = visibleMonths.map((month) => capacityRows.reduce((balance, provider) => {
        const code = provider.code || provider.cnes || provider.label;
        const row = rowsByProviderMonth.get(`${month}:${code}`);
        const days = new Date(activeYear, month, 0).getDate();
        const daily = (Number(row?.dailyCount) || 0) + (Number(row?.rejectedDays) || 0);
        return balance + (Number(provider.bedsSus) || 0) - (days ? daily / days : 0);
      }, 0));
      return {
        bedsSus:beds,
        aihCount:processed,
        dailyCount:actualDays,
        averageDaily:calendarDays ? actualDays / calendarDays : null,
        occupancyRate:bedDays ? actualDays / bedDays * 100 : null,
        potentialBalance:monthlyBalances.length ? monthlyBalances.reduce((total, value) => total + value, 0) / monthlyBalances.length : null,
        rejectionRate:processed + rejected ? rejected / (processed + rejected) * 100 : 0,
        rejectedCount:rejected
      };
    }
    const daysInMonth = Number(activeResult?.daysInMonth) || 0;
    const knownBedRows = rows.filter((row) => row.bedsSus != null && row.bedsSus !== '');
    const allBedsKnown = knownBedRows.length === rows.length;
    const beds = allBedsKnown ? sum('bedsSus') : null;
    const actualDays = sum('dailyCount');
    const knownActualDays = knownBedRows.reduce((total, row) => total + (Number(row.dailyCount) || 0), 0);
    const rejectedDays = knownBedRows.reduce((total, row) => total + (Number(row.rejectedDays) || 0), 0);
    const processed = sum('aihCount');
    const rejected = sum('rejectedCount');
    const average = daysInMonth ? actualDays / daysInMonth : 0;
    const potentialAverage = daysInMonth ? (knownActualDays + rejectedDays) / daysInMonth : 0;
    return {
      bedsSus:beds, aihCount:processed, dailyCount:actualDays,
      averageDaily:average, occupancyRate:beds ? knownActualDays / daysInMonth / beds * 100 : null,
      potentialBalance:beds == null ? null : beds - potentialAverage,
      rejectionRate:processed + rejected ? rejected / (processed + rejected) * 100 : 0,
      rejectedCount:rejected
    };
  }

  function renderTablePagination(totalRows, pageCount) {
    const info = $('reportPageInfo');
    if (info) info.textContent = totalRows ? `Página ${formatNumber(tablePage)} de ${formatNumber(pageCount)}` : 'Nenhuma linha';
    const previous = $('reportPagePrevious');
    const next = $('reportPageNext');
    if (previous) previous.disabled = tablePage <= 1;
    if (next) next.disabled = tablePage >= pageCount;
    const size = $('reportPageSize');
    if (size && size.value !== String(tablePageSize)) size.value = String(tablePageSize);
  }

  function closeColumnFilterMenu() {
    if (columnFilterMenu?.node?.isConnected) columnFilterMenu.node.remove();
    columnFilterMenu = null;
  }

  function resetTableViewState() {
    closeColumnFilterMenu();
    columnFilters = new Map();
    sortState = null;
    tablePage = 1;
  }

  function tableSettings() {
    const columns = tableColumns();
    const filters = {};
    for (const [columnId, excluded] of columnFilters) {
      const column = columns.find((item) => item.id === columnId && item.filterable);
      if (!column || !excluded.size) continue;
      const available = [...new Set(allRows.map((row) => columnFilterToken(row, column)))];
      const included = available.filter((token) => !excluded.has(token));
      const removed = available.filter((token) => excluded.has(token));
      filters[columnId] = included.length <= removed.length
        ? { mode:'include', values:included }
        : { mode:'exclude', values:removed };
    }
    return { search:$('reportSearch').value.trim().slice(0, 120), sort:sortState, columns:filters };
  }

  function restoreTableDefaults() {
    const saved = reportDefaults.get(activeReport.id)?.table?.[activeView];
    if (!saved || typeof saved !== 'object') return;
    $('reportSearch').value = typeof saved.search === 'string' ? saved.search.slice(0, 120) : '';
    const columns = tableColumns();
    const sortable = columns.find((column) => column.id === saved.sort?.columnId && column.sortable);
    sortState = sortable && ['asc', 'desc'].includes(saved.sort.direction) ? { columnId:sortable.id, direction:saved.sort.direction } : null;
    for (const [columnId, setting] of Object.entries(saved.columns || {})) {
      const column = columns.find((item) => item.id === columnId && item.filterable);
      if (!column || !setting || !Array.isArray(setting.values)) continue;
      const values = new Set(setting.values.filter((item) => typeof item === 'string'));
      const excluded = setting.mode === 'include'
        ? new Set(allRows.map((row) => columnFilterToken(row, column)).filter((token) => !values.has(token)))
        : new Set(values);
      if (excluded.size) columnFilters.set(columnId, excluded);
    }
  }

  function updateTableDefaultControls() {
    const saved = reportDefaults.get(activeReport.id)?.table?.[activeView];
    const hasFilters = Boolean($('reportSearch').value.trim() || columnFilters.size || sortState);
    $('tableDefaultActions').hidden = !saved && !hasFilters;
    $('clearTableDefault').hidden = !saved;
    $('saveTableDefault').textContent = saved ? 'Atualizar padrão' : 'Salvar filtros como padrão';
  }

  async function saveTableDefault() {
    const button = $('saveTableDefault');
    button.disabled = true;
    try {
      const data = await api({ action:'report_defaults_save', report:activeReport.id, scope:'table', view:activeView, settings:tableSettings() });
      reportDefaults.set(activeReport.id, data.defaults || {});
      updateTableDefaultControls();
      button.textContent = 'Padrão salvo';
    } catch (error) { showNotice(error.message || 'Não foi possível salvar os filtros.', 'error'); }
    finally { button.disabled = false; }
  }

  async function clearTableDefault() {
    const button = $('clearTableDefault');
    button.disabled = true;
    try {
      const data = await api({ action:'report_defaults_delete', report:activeReport.id, scope:'table', view:activeView });
      reportDefaults.set(activeReport.id, data.defaults || {});
      updateTableDefaultControls();
    } catch (error) { showNotice(error.message || 'Não foi possível remover os filtros salvos.', 'error'); }
    finally { button.disabled = false; }
  }

  function positionColumnFilterMenu() {
    if (!columnFilterMenu?.node?.isConnected) return;
    const menu = columnFilterMenu.node;
    const anchor = columnFilterMenu.anchor;
    const rect = anchor.getBoundingClientRect();
    const width = Math.min(350, window.innerWidth - 20);
    menu.style.width = `${width}px`;
    menu.style.left = `${Math.max(10, Math.min(window.innerWidth - width - 10, rect.right - width))}px`;
    const menuHeight = menu.getBoundingClientRect().height;
    const below = rect.bottom + 8;
    menu.style.top = `${below + menuHeight <= window.innerHeight - 10 ? below : Math.max(10, rect.top - menuHeight - 8)}px`;
  }

  function drawColumnFilterOptions() {
    if (!columnFilterMenu) return;
    const { column, node, pending, search, values } = columnFilterMenu;
    const list = node.querySelector('.report-column-filter-options');
    const count = node.querySelector('.report-column-filter-count');
    list.replaceChildren();
    const query = search.value.trim().toLocaleLowerCase('pt-BR');
    const matching = [...values.entries()].filter(([, label]) => !query || label.toLocaleLowerCase('pt-BR').includes(query));
    matching.sort((a, b) => a[1].localeCompare(b[1], 'pt-BR', { numeric:true, sensitivity:'base' }));
    const limit = 300;
    for (const [token, label] of matching.slice(0, limit)) {
      const option = document.createElement('label'); option.className = 'report-column-filter-option';
      const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.checked = !pending.has(token);
      checkbox.addEventListener('change', () => {
        if (checkbox.checked) pending.delete(token); else pending.add(token);
        count.textContent = `${formatNumber(Math.max(0, values.size - pending.size))} selecionados de ${formatNumber(values.size)}`;
      });
      option.append(checkbox, buildCell('span', label || '(Vazio)')); list.append(option);
    }
    if (!matching.length) list.append(buildCell('p', 'Nenhum valor encontrado.', 'report-column-filter-empty'));
    const remainder = matching.length - limit;
    const selectedCount = Math.max(0, values.size - [...pending].filter((token) => values.has(token)).length);
    const matchingSelectedCount = matching.filter(([token]) => !pending.has(token)).length;
    count.textContent = `${formatNumber(selectedCount)} de ${formatNumber(values.size)} selecionados${remainder > 0 ? ` · ${formatNumber(remainder)} correspondências não exibidas` : ''}`;
    const selectAll = node.querySelector('[data-filter-bulk="select"]');
    const deselectAll = node.querySelector('[data-filter-bulk="deselect"]');
    const clear = node.querySelector('[data-filter-clear]');
    selectAll.disabled = matchingSelectedCount === matching.length;
    deselectAll.disabled = matchingSelectedCount === 0 || matching.length === 0;
    clear.disabled = !columnFilters.has(column.id);
    positionColumnFilterMenu();
  }

  function openColumnFilterMenu(column, anchor) {
    closeColumnFilterMenu();
    const values = new Map();
    for (const row of rowsMatchingFilters(column.id)) {
      const token = columnFilterToken(row, column);
      if (!values.has(token)) values.set(token, columnDisplayValue(row, column));
    }
    const node = document.createElement('div'); node.className = 'report-column-filter-menu';
    node.setAttribute('role', 'dialog'); node.setAttribute('aria-label', `Filtro da coluna ${column.label}`);
    const title = buildCell('strong', column.label, 'report-column-filter-title');
    const search = document.createElement('input'); search.type = 'search'; search.className = 'report-column-filter-search'; search.placeholder = 'Pesquisar valores…'; search.setAttribute('aria-label', `Pesquisar valores em ${column.label}`);
    const count = buildCell('span', '', 'report-column-filter-count');
    count.setAttribute('aria-live', 'polite');
    const list = document.createElement('div'); list.className = 'report-column-filter-options';
    const controls = document.createElement('div'); controls.className = 'report-column-filter-controls';
    const selectAll = buildCell('button', 'Selecionar todos', 'report-column-filter-link'); selectAll.type = 'button'; selectAll.dataset.filterBulk = 'select';
    selectAll.title = 'Marca todos os valores encontrados na pesquisa; com a busca vazia, marca todos.';
    selectAll.addEventListener('click', () => {
      const query = search.value.trim().toLocaleLowerCase('pt-BR');
      if (!query) columnFilterMenu.pending.clear();
      else for (const [token, label] of values) if (label.toLocaleLowerCase('pt-BR').includes(query)) columnFilterMenu.pending.delete(token);
      drawColumnFilterOptions();
    });
    const deselectAll = buildCell('button', 'Desmarcar todos', 'report-column-filter-link'); deselectAll.type = 'button'; deselectAll.dataset.filterBulk = 'deselect';
    deselectAll.title = 'Desmarca todos os valores encontrados na pesquisa; com a busca vazia, desmarca todos.';
    deselectAll.addEventListener('click', () => {
      const query = search.value.trim().toLocaleLowerCase('pt-BR');
      for (const [token, label] of values) if (!query || label.toLocaleLowerCase('pt-BR').includes(query)) columnFilterMenu.pending.add(token);
      drawColumnFilterOptions();
    });
    const clear = buildCell('button', 'Limpar filtro', 'report-column-filter-link'); clear.type = 'button'; clear.dataset.filterClear = 'true';
    clear.addEventListener('click', () => { columnFilters.delete(column.id); tablePage = 1; closeColumnFilterMenu(); renderTable(); });
    controls.append(selectAll, deselectAll, clear);
    const scopeHint = buildCell('span', 'Com pesquisa, as ações valem para os resultados encontrados.', 'report-column-filter-bulk-note');
    const sort = document.createElement('div'); sort.className = 'report-column-filter-sort';
    const ascending = buildCell('button', column.type === 'number' || column.type === 'currency' ? 'Menor para maior' : 'A → Z', 'report-column-filter-sort-button'); ascending.type = 'button';
    const descending = buildCell('button', column.type === 'number' || column.type === 'currency' ? 'Maior para menor' : 'Z → A', 'report-column-filter-sort-button'); descending.type = 'button';
    ascending.addEventListener('click', () => { sortState = { columnId:column.id, direction:'asc' }; tablePage = 1; closeColumnFilterMenu(); renderTable(); });
    descending.addEventListener('click', () => { sortState = { columnId:column.id, direction:'desc' }; tablePage = 1; closeColumnFilterMenu(); renderTable(); });
    sort.append(ascending, descending);
    const footer = document.createElement('div'); footer.className = 'report-column-filter-footer';
    const cancel = buildCell('button', 'Cancelar', 'report-column-filter-cancel'); cancel.type = 'button'; cancel.addEventListener('click', closeColumnFilterMenu);
    const apply = buildCell('button', 'Aplicar filtro', 'report-column-filter-apply'); apply.type = 'button';
    apply.addEventListener('click', () => {
      if (columnFilterMenu.pending.size) columnFilters.set(column.id, new Set(columnFilterMenu.pending)); else columnFilters.delete(column.id);
      tablePage = 1; closeColumnFilterMenu(); renderTable();
    });
    footer.append(cancel, apply);
    node.append(title, search, controls, scopeHint, count, list, sort, footer);
    node.addEventListener('click', (event) => event.stopPropagation());
    search.addEventListener('input', drawColumnFilterOptions);
    columnFilterMenu = { node, column, anchor, pending:new Set(columnFilters.get(column.id) || []), search, values };
    document.body.append(node);
    drawColumnFilterOptions();
    search.focus({ preventScroll:true });
  }

  function rememberResult(view, cnes, data, aih = activeAih, months = activeMonths) {
    const key = resultKey(view, cnes, view === 'services' ? aih : '', months);
    results.set(key, data);
    return data;
  }

  function resultKey(view, cnes, aih = '', months = activeMonths) {
    const filters = selectedFilters();
    return JSON.stringify([activeReport.id, activeYear, [...months], filters.uf, filters.municipalityCode, ...Object.values(filterDefinitions).map((definition) => filters[definition.field]), view, cnes || '', aih || '']);
  }

  function cachedResult(view, cnes, aih = '', months = activeMonths) {
    return results.get(resultKey(view, cnes, aih, months));
  }

  function routeUrl(view, cnes = '', aih = '', months = activeMonths) {
    const next = new URL(location.href);
    const filters = selectedFilters();
    next.searchParams.set('relatorio', activeReport.id);
    next.searchParams.set('ano', String(activeYear));
    next.searchParams.delete('mes');
    for (const month of months) next.searchParams.append('mes', String(month));
    next.searchParams.set('uf', filters.uf);
    const queryValues = [['municipio', filters.municipalityCode], ...Object.values(filterDefinitions).map((definition) => [definition.queryKey, filters[definition.field]])];
    for (const [key, rawValues] of queryValues) {
      next.searchParams.delete(key);
      for (const value of normalizeSelectedValues(rawValues)) next.searchParams.append(key, value);
    }
    if (view !== 'summary' && cnes) next.searchParams.set('cnes', cnes); else next.searchParams.delete('cnes');
    if (view === 'services' && aih) next.searchParams.set('aih', aih); else next.searchParams.delete('aih');
    history.pushState({ view, cnes, aih }, '', next);
  }

  function reportKindsForView(view) {
    const requiredKinds = activeReport.kindsByView?.[view] || activeReport.requiredKinds || [activeReport.kind];
    const optionalKinds = view === 'detail' ? (activeReport.optionalKinds || []) : [];
    return { requiredKinds, optionalKinds, kinds:[...new Set([...requiredKinds, ...optionalKinds])] };
  }

  async function findOrDownloadFile(year, month, uf) {
    const local = localFor(year, month, uf);
    if (local) return local;
    setLoader(true, 'Consultando o arquivo oficial', `Localizando ${activeReport.sourceLabel} de ${stateNames[uf]} · ${monthNames[month - 1]} de ${year} no DATASUS.`, null, true);
    const listing = await api({ action: 'files', system: activeReport.system, year: Number(year), month: Number(month), uf });
    const prefix = `${activeReport.kind}${uf}${String(year).slice(-2)}${String(month).padStart(2, '0')}`;
    const file = (listing.files || []).find((item) => item.kind === activeReport.kind && String(item.uf || '').toUpperCase() === uf && item.name?.toUpperCase().startsWith(prefix));
    if (!file) throw new Error(`O DATASUS ainda não disponibilizou o arquivo ${activeReport.kind} desta competência para ${stateNames[uf]}.`);
    if (file.downloaded && file.local_path) {
      const item = { ...file, path: file.local_path, system: activeReport.systemCode, year: Number(year), month: Number(month), uf };
      addLocalFiles([item]); return item;
    }
    setLoader(true, 'Baixando o DBC oficial', `${file.name} · o tempo depende da conexão com o DATASUS.`, null, true);
    const downloaded = await api({ action: 'download', system: activeReport.system, year: Number(year), month: Number(month), uf, names: [file.name] });
    const saved = (downloaded.files || []).find((item) => item.name?.toUpperCase() === file.name.toUpperCase());
    if (!saved?.path) throw new Error('O DATASUS não confirmou a gravação do arquivo baixado.');
    const item = { ...file, ...saved, system: activeReport.systemCode, kind: activeReport.kind, uf, year: Number(year), month: Number(month), path: saved.path };
    addLocalFiles([item]);
    return item;
  }

  async function findOrDownloadReportFiles(year, month, uf, view = 'summary', localOnly = false) {
    const { requiredKinds, optionalKinds, kinds } = reportKindsForView(view);
    const filesByKind = {};
    for (const kind of kinds) {
      const local = localForKind(year, month, uf, kind);
      if (local) {
        filesByKind[kind] = local;
        updateDownloadTask(year, month, kind, 'ready');
      } else updateDownloadTask(year, month, kind, 'checking');
    }
    if (kinds.every((kind) => filesByKind[kind])) return filesByKind;
    if (localOnly) {
      if (!requiredKinds.every((kind) => filesByKind[kind])) throw new Error(`Para consultar várias competências, baixe antes os arquivos de ${monthNames[month - 1]} de ${year} na biblioteca.`);
      for (const kind of optionalKinds) if (!filesByKind[kind]) updateDownloadTask(year, month, kind, 'unavailable');
      return filesByKind;
    }

    setLoader(true, 'Consultando os arquivos oficiais', `${stateNames[uf]} · ${monthNames[month - 1]} de ${year} · localizando ${kinds.map((kind) => `SIH/${kind}`).join(' e ')} no DATASUS.`, null, true);
    let listing;
    try {
      listing = await api({ action:'files', system:activeReport.system, year:Number(year), month:Number(month), uf });
    } catch (error) {
      if (requiredKinds.every((kind) => filesByKind[kind])) {
        for (const kind of optionalKinds) if (!filesByKind[kind]) updateDownloadTask(year, month, kind, 'unavailable');
        return filesByKind;
      }
      for (const kind of requiredKinds) if (!filesByKind[kind]) updateDownloadTask(year, month, kind, 'error');
      throw error;
    }
    const pendingDownloads = [];
    for (const kind of kinds) {
      if (filesByKind[kind]) continue;
      const prefix = `${kind}${uf}${String(year).slice(-2)}${String(month).padStart(2, '0')}`;
      const file = (listing.files || []).find((item) => item.kind === kind && String(item.uf || '').toUpperCase() === uf && item.name?.toUpperCase().startsWith(prefix));
      if (!file) {
        if (requiredKinds.includes(kind)) {
          updateDownloadTask(year, month, kind, 'error');
          throw new Error(`O DATASUS ainda não disponibilizou o arquivo SIH/${kind} desta competência para ${stateNames[uf]}.`);
        }
        updateDownloadTask(year, month, kind, 'unavailable');
        continue;
      }
      if (file.downloaded && file.local_path) {
        const item = { ...file, path:file.local_path, system:activeReport.systemCode, year:Number(year), month:Number(month), uf, kind };
        filesByKind[kind] = item;
        addLocalFiles([item]);
        updateDownloadTask(year, month, kind, 'ready');
      } else pendingDownloads.push({ kind, file });
    }
    const orderedDownloads = [
      ...pendingDownloads.filter(({ kind }) => requiredKinds.includes(kind)),
      ...pendingDownloads.filter(({ kind }) => optionalKinds.includes(kind))
    ];
    for (const { kind, file } of orderedDownloads) {
      const optional = optionalKinds.includes(kind);
      const taskIndex = [...downloadTasks.keys()].indexOf(downloadTaskKey(year, month, kind)) + 1;
      updateDownloadTask(year, month, kind, 'downloading', file.name);
      setLoader(true, taskIndex ? `Baixando arquivo ${taskIndex} de ${downloadTasks.size}` : 'Baixando arquivo DATASUS', `${file.name} · ${monthNames[month - 1]} de ${year}. Aguarde a conclusão antes do próximo arquivo.`, null, true);
      try {
        const downloaded = await api({ action:'download', system:activeReport.system, year:Number(year), month:Number(month), uf, names:[file.name] });
        const saved = (downloaded.files || []).find((item) => item.name?.toUpperCase() === file.name.toUpperCase());
        if (!saved?.path) throw new Error(`O DATASUS não confirmou a gravação do arquivo ${file.name}.`);
        const item = { ...file, ...saved, system:activeReport.systemCode, kind, uf, year:Number(year), month:Number(month), path:saved.path };
        filesByKind[kind] = item;
        addLocalFiles([item]);
        updateDownloadTask(year, month, kind, 'ready', file.name);
      } catch (error) {
        updateDownloadTask(year, month, kind, 'error');
        if (optional) continue;
        throw error;
      }
    }
    for (const kind of requiredKinds) {
      if (!filesByKind[kind]) throw new Error(`Não foi possível localizar o arquivo SIH/${kind} desta competência.`);
    }
    return filesByKind;
  }

  async function ensureConverted(file) {
    setLoader(true, 'Preparando a base para leitura', `${file.name} · verificando a cópia convertida neste computador.`, null, true);
    let conversion = await api({ action: 'convert_start', path: file.path });
    if (conversion.done && conversion.dbf_path) return conversion.dbf_path;
    if (!conversion.job_id) throw new Error('O SPPtab não retornou uma tarefa de preparação válida.');
    const conversionJobId = conversion.job_id;
    while (true) {
      setLoader(true, conversion.stage || 'Preparando a base para leitura', conversion.message || `${file.name} · leitura em andamento.`, conversion.progress ?? 1);
      await new Promise((resolve) => setTimeout(resolve, 900));
      conversion = await api({ action: 'convert_status', job_id: conversionJobId });
      if (conversion.status === 'error') throw new Error(conversion.message || 'Não foi possível preparar o arquivo.');
      if (conversion.status === 'done') {
        if (!conversion.dbf_path) throw new Error('A preparação terminou sem localizar a base pronta.');
        return conversion.dbf_path;
      }
    }
  }

  function stampMonthlyResult(data, year, month) {
    const competence = `${String(month).padStart(2, '0')}/${year}`;
    return {
      ...data,
      year,
      month,
      competence,
      rows: (data.rows || []).map((row) => ({
        ...row,
        competence,
        _competenceMonth: month,
        _competenceYear: year,
        _monthDays: Number(data.daysInMonth) || Number(row._monthDays) || 0
      }))
    };
  }

  function combineMonthlyKpis(monthlyResults, rows, months, year) {
    const first = monthlyResults[0]?.kpis;
    if (!Array.isArray(first)) return undefined;
    if (months.length === 1) return first;
    return first.map((item, index) => {
      const label = String(item.label || '');
      if (/estabelecimentos/i.test(label)) {
        const count = new Set(rows.map((row) => String(row.code || row.cnes || '')).filter(Boolean)).size;
        return { ...item, value:{ value:count } };
      }
      if (/ocupa[cç][aã]o/i.test(label)) {
        const capacityByProvider = new Map();
        for (const row of rows) {
          const code = String(row.code || row.cnes || row.label || '');
          const previous = capacityByProvider.get(code);
          if (!previous || Number(row._competenceMonth) > Number(previous._competenceMonth)) capacityByProvider.set(code, row);
        }
        const capacityRows = [...capacityByProvider.values()].filter((row) => row.bedsSus != null && row.bedsSus !== '');
        const knownCodes = new Set(capacityRows.map((row) => String(row.code || row.cnes || row.label || '')));
        const numerator = rows.filter((row) => knownCodes.has(String(row.code || row.cnes || row.label || ''))).reduce((sum, row) => sum + (Number(row.dailyCount) || 0), 0);
        const totalDays = months.reduce((sum, month) => sum + new Date(year, month, 0).getDate(), 0);
        const totalBeds = capacityRows.reduce((sum, row) => sum + (Number(row.bedsSus) || 0), 0);
        const denominator = totalBeds * totalDays;
        return denominator ? { ...item, value:{ ...(typeof item.value === 'object' ? item.value : {}), value:numerator / denominator * 100 } } : { ...item, value:{ text:'—' } };
      }
      const values = monthlyResults.map((result) => result.kpis?.[index]?.value);
      const numeric = values.map((value) => typeof value === 'number' ? value : value && typeof value === 'object' && Number.isFinite(Number(value.value)) ? Number(value.value) : null);
      if (numeric.some((value) => value === null)) return item;
      const total = numeric.reduce((sum, value) => sum + value, 0);
      const template = values.find((value) => value && typeof value === 'object') || {};
      return { ...item, value:{ ...template, value:total } };
    });
  }

  function combineMonthlyResults(monthlyResults, months, year) {
    const first = monthlyResults[0];
    const rows = monthlyResults.flatMap((result) => result.rows || []);
    const files = [...new Set(monthlyResults.flatMap((result) => result.files?.length ? result.files : result.file ? [result.file] : []))];
    const emptyMonths = monthlyResults.filter((result) => !(result.rows || []).length).map((result) => monthNames[result.month - 1]);
    const notes = [...new Set(monthlyResults.flatMap((result) => result.notes || []))];
    if (emptyMonths.length) notes.push(`Sem registros compatíveis nos meses: ${emptyMonths.join(', ')} de ${year}.`);
    const combined = {
      ...first,
      year,
      month:months[0],
      months:[...months],
      rows,
      records:monthlyResults.reduce((total, result) => total + (Number(result.records) || 0), 0),
      files,
      file:files.length === 1 ? files[0] : `${files.length} arquivos DATASUS`,
      notes,
      kpis:combineMonthlyKpis(monthlyResults, rows, months, year)
    };
    if (monthlyResults.some((result) => result.totalAIHs != null)) combined.totalAIHs = monthlyResults.reduce((total, result) => total + (Number(result.totalAIHs) || 0), 0);
    return combined;
  }

  async function tabulateReportMonth(view, cnes, aih, filters, year, month, monthIndex, monthCount) {
    const filesByKind = await findOrDownloadReportFiles(year, month, filters.uf, view, monthCount > 1);
    const dbfPaths = {};
    const { kinds } = reportKindsForView(view);
    for (const kind of kinds) {
      if (filesByKind[kind]) dbfPaths[kind] = await ensureConverted(filesByKind[kind]);
    }
    const sourceKind = activeReport.tableMode === 'occupancy' && view === 'services' ? 'SP' : activeReport.kind;
    const file = filesByKind[sourceKind];
    const dbfPath = dbfPaths[sourceKind];
    const filterDescription = [filters.municipalityName, ...Object.values(filterDefinitions).filter((definition) => filters[definition.nameField].length).map((definition) => summarizeSelectedNames(filters[definition.nameField]))].filter(Boolean).join(' · ');
    const detailLabel = view === 'services' ? `os serviços profissionais da AIH ${aih}` : `${activeReport.detailPrefix || 'as AIHs'} do CNES ${cnes}`;
    const monthProgress = Math.round(monthIndex / monthCount * 100);
    setLoader(true, `Preparando competência ${monthIndex + 1} de ${monthCount}`, view === 'summary' ? `${monthNames[month - 1]} de ${year} · ${filterDescription || stateNames[filters.uf]} · agrupando os valores por estabelecimento.` : `${monthNames[month - 1]} de ${year} · consultando ${detailLabel}.`, monthProgress);
    const sourcePaths = {};
    if (activeReport.id === 'sih-rd-rejeicoes' || (activeReport.id === 'sih-rd-ocupacao' && view !== 'services')) {
      sourcePaths.rejectedPath = filesByKind.RJ.path;
      sourcePaths.rejectedDbfPath = dbfPaths.RJ;
      if (filesByKind.ER) {
        sourcePaths.errorPath = filesByKind.ER.path;
        sourcePaths.errorDbfPath = dbfPaths.ER;
      }
    } else if (activeReport.id === 'sih-rd-ocupacao' && view === 'services') {
      sourcePaths.professionalPath = filesByKind.SP.path;
      sourcePaths.professionalDbfPath = dbfPaths.SP;
    }
    let job = await api({ action:'tabulate_start', path:file.path, dbfPath, ...sourcePaths, predefinedReport:activeReport.id, predefinedView:view, ...filters, ...((view === 'detail' || view === 'services') ? { establishmentCode:cnes } : {}), ...(view === 'services' ? { aih } : {}) });
    if (job.done && job.result) return stampMonthlyResult(job.result, year, month);
    if (!job.job_id) throw new Error('O SPPtab não retornou uma tarefa de tabulação válida.');
    const tabulationJobId = job.job_id;
    while (true) {
      const localProgress = Math.max(0, Math.min(100, Number(job.progress) || 1));
      setLoader(true, job.stage || `Montando competência ${monthIndex + 1} de ${monthCount}`, `${monthNames[month - 1]} de ${year} · ${job.message || `Aplicando os filtros selecionados · ${stateNames[filters.uf]}.`}`, Math.min(99, (monthIndex + localProgress / 100) / monthCount * 100));
      await new Promise((resolve) => setTimeout(resolve, 850));
      job = await api({ action:'tabulate_status', job_id:tabulationJobId });
      if (job.status === 'error') throw new Error(job.message || `Não foi possível tabular ${monthNames[month - 1]} de ${year}.`);
      if (job.status === 'done') {
        if (!job.result?.ok) throw new Error(job.result?.error || `O resultado de ${monthNames[month - 1]} de ${year} não foi concluído.`);
        return stampMonthlyResult(job.result, year, month);
      }
    }
  }

  async function runReport(view = 'summary', cnes = '', updateUrl = true, aih = '', monthList = null) {
    const year = Number(yearSelect.value) || activeYear;
    let requestedMonths = [...new Set((monthList == null ? (view === 'services' ? [activeMonth] : (reportMonths.length ? reportMonths : selectedMonths())) : monthList).map(Number).filter((month) => month >= 1 && month <= 12))].sort((a, b) => a - b);
    if (!year || !requestedMonths.length) return;
    const requestedCount = requestedMonths.length;
    requestedMonths = allowedMonths(requestedMonths, year, selectedUf()).sort((a, b) => a - b);
    if (requestedCount > 1 && requestedMonths.length === 1) setSelectedMonths(requestedMonths);
    if (view === 'summary') reportMonths = [...requestedMonths];
    const filters = selectedFilters();
    activeYear = year; activeMonths = requestedMonths; activeMonth = requestedMonths.at(-1); activeView = view; activeCnes = cnes; activeAih = aih;
    resetTableViewState();
    $('reportSearch').value = '';
    showNotice('');
    resultPanel.hidden = true;
    empty.hidden = true;
    openButton.disabled = true;
    const setupSelects = [ufSelect, municipalitySelect, yearSelect, monthSelect, addFilterSelect, ...addedFilterRows.querySelectorAll('select')];
    for (const select of setupSelects) select.disabled = true;
    updateMonthPicker();
    if (updateUrl) routeUrl(view, cnes, aih, requestedMonths);
    const cached = cachedResult(view, cnes, aih, requestedMonths);
    if (cached) {
      activeResult = cached; allRows = cached.rows || [];
      restoreTableDefaults();
      setLoader(false); renderTable();
      for (const select of setupSelects) select.disabled = false;
      updateMonthPicker();
      openButton.disabled = selectedMonths().length === 0; return;
    }

    beginDownloadQueue(year, requestedMonths, view);
    try {
      const monthlyResults = [];
      for (const [index, month] of requestedMonths.entries()) {
        monthlyResults.push(await tabulateReportMonth(view, cnes, aih, filters, year, month, index, requestedMonths.length));
      }
      activeResult = combineMonthlyResults(monthlyResults, requestedMonths, year);
      rememberResult(view, cnes, activeResult, aih, requestedMonths);
      allRows = activeResult.rows || [];
      restoreTableDefaults();
      setLoader(false);
      renderTable();
      setAvailability(`${formatCompetencies(requestedMonths, year)} · resultado pronto neste computador.`, 'good');
    } catch (error) {
      showReportFailure(error);
    } finally {
      for (const select of setupSelects) select.disabled = false;
      monthSelect.disabled = ![...monthSelect.options].some((option) => Number(option.value) >= 1 && Number(option.value) <= 12);
      updateMonthPicker();
      openButton.disabled = monthSelect.disabled || selectedMonths().length === 0;
    }
  }

  function exportCsv() {
    if (!activeResult) return;
    const rows = visibleRows();
    const columns = tableColumns().filter((column) => column.kind !== 'action');
    const metrics = activeResult.metrics || [];
    const customTotals = activeReport.tableMode === 'occupancy' ? occupancyTotalsFor(rows) : null;
    const csvRows = [columns.map((column) => column.label)];
    for (const row of rows) csvRows.push(columns.map((column) => column.metricId ? `${column.type === 'currency' ? 'R$ ' : ''}${formatNumber(rawColumnValue(row, column), column.decimals)}` : columnDisplayValue(row, column)));
    const totals = totalsFor(rows, metrics);
    const totalRow = columns.map((column, index) => {
      if (column.metricId) {
        const metricIndex = metrics.findIndex((metric) => metric.id === column.metricId);
        if (metricIndex >= 0) return `${column.type === 'currency' ? 'R$ ' : ''}${formatScaled(totals[metricIndex], metrics[metricIndex].decimals)}`;
      }
      if (customTotals && column.totalField) {
        const raw = Object.prototype.hasOwnProperty.call(customTotals, column.totalField) ? customTotals[column.totalField] : rows.reduce((sum, row) => sum + (Number(String(row[column.totalField] ?? '').replace(',', '.')) || 0), 0);
        const formatted = raw == null ? '' : formatNumber(raw, column.decimals);
        return column.type === 'currency' && formatted ? `R$ ${formatted}` : column.type === 'percent' && formatted ? `${formatted}%` : formatted;
      }
      return index === 0 ? 'Total visível' : '';
    });
    csvRows.push(totalRow);
    const escape = (value) => `"${String(value ?? '').replaceAll('"', '""')}"`;
    const csv = '\uFEFF' + csvRows.map((row) => row.map(escape).join(';')).join('\r\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    const scope = [activeResult.uf, activeResult.municipalityCode || 'UF'].filter(Boolean).join('-');
    const periodToken = activeMonths.length === 12 ? 'anual' : activeMonths.map((month) => String(month).padStart(2, '0')).join('-');
    link.href = url; link.download = `SPPtab-${activeResult.report || activeReport.id}-${scope}-${activeYear}-${periodToken}.csv`;
    document.body.append(link); link.click(); link.remove(); URL.revokeObjectURL(url);
  }

  function setYears() {
    const current = new Date().getFullYear();
    yearSelect.replaceChildren();
    for (let year = current; year >= 2008; year -= 1) yearSelect.add(new Option(String(year), String(year)));
    yearSelect.disabled = false;
    yearSelect.value = String(linkedYear >= 2008 && linkedYear <= current ? linkedYear : current);
  }

  async function generateConfiguredReport() {
    const year = Number(yearSelect.value);
    const months = selectedMonths();
    if (!year || !months.length) {
      setAvailability('Escolha pelo menos uma competência disponível antes de gerar o relatório.', 'error');
      return;
    }
    reportMonths = months;
    if (setupDialog.open) setupDialog.close();
    setPageView('report', false);
    clearPreviousResult();
    await runReport('summary', '', true, '', months);
  }

  for (const reportCard of document.querySelectorAll('.predefined-card[data-report]')) {
    const activate = async () => {
      const preferredUf = selectedUf();
      const reportId = reportCard.dataset.report;
      if (!activateReport(reportId)) return;
      await loadReportDefaults(reportId);
      if (activeReport.id !== reportId) return;
      const preferred = applySetupPreference(preferredUf);
      await openReportSetup(preferred);
    };
    reportCard.addEventListener('click', activate);
    reportCard.addEventListener('keydown', (event) => {
      if (event.target !== reportCard || !['Enter', ' '].includes(event.key)) return;
      event.preventDefault();
      activate();
    });
  }
  $('backToCatalog').addEventListener('click', () => returnToCatalog(true));
  $('editReportCriteria').addEventListener('click', () => openReportSetup());
  $('configureReportFromEmpty').addEventListener('click', () => openReportSetup());
  $('closeReportSetup').addEventListener('click', () => setupDialog.close());
  $('cancelReportSetup').addEventListener('click', () => setupDialog.close());
  $('saveSetupDefault').addEventListener('click', saveSetupDefault);
  $('clearSetupDefault').addEventListener('click', clearSetupDefault);
  $('saveTableDefault').addEventListener('click', saveTableDefault);
  $('clearTableDefault').addEventListener('click', clearTableDefault);
  openButton.addEventListener('click', generateConfiguredReport);
  function clearPreviousResult() {
    resultPanel.hidden = true;
    activeResult = null;
    allRows = [];
    results.clear();
    resetTableViewState();
    showNotice('');
    empty.hidden = false;
    $('reportEmpty').querySelector('strong').textContent = 'Configure o recorte do relatório';
    $('reportEmptyMessage').textContent = activeReport.emptyMessage;
  }
  yearSelect.addEventListener('change', async () => {
    await refreshCompetencies(Number(yearSelect.value), [], selectedUf());
    updateScopeDescription();
  });
  ufSelect.addEventListener('change', async () => {
    const preferred = selectedFilters();
    updateScopeDescription();
    await Promise.all([refreshCompetencies(Number(yearSelect.value), [], selectedUf()), loadOptionalFilters(selectedUf(), preferred)]);
    updateScopeDescription();
  });
  municipalitySelect.addEventListener('change', () => {
    const preferred = selectedFilters();
    renderAdditionalFilterRows(preferred);
  });
  monthSelect.addEventListener('change', () => {
    updateMonthPicker();
    updateScopeDescription();
    openButton.disabled = selectedMonths().length === 0;
  });
  monthPickerTrigger.addEventListener('click', () => {
    const opening = monthPickerMenu.hidden;
    monthPickerMenu.hidden = !opening;
    monthPickerTrigger.setAttribute('aria-expanded', String(opening));
  });
  monthPickerTrigger.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape' || monthPickerMenu.hidden) return;
    event.preventDefault();
    closeMonthPicker(true);
  });
  monthPickerOptions.addEventListener('change', (event) => {
    if (!event.target.matches('input[type="checkbox"]')) return;
    const month = Number(event.target.value);
    const current = selectedMonths().filter((item) => item !== month);
    setSelectedMonths(event.target.checked ? [...current, month] : current);
  });
  $('clearReportMonths').addEventListener('click', () => setSelectedMonths([]));
  monthPickerMenu.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeMonthPicker(true);
    }
  });
  document.addEventListener('pointerdown', (event) => {
    if (!monthPicker.contains(event.target)) closeMonthPicker();
  });
  addFilterSelect.addEventListener('change', () => {
    const preferred = selectedFilters();
    const type = addFilterSelect.value;
    if (type && filterDefinitions[type] && !activeFilterTypes.includes(type)) activeFilterTypes.push(type);
    addFilterSelect.value = '';
    renderAdditionalFilterRows(preferred);
  });
  addedFilterRows.addEventListener('click', (event) => {
    const button = event.target.closest('[data-remove-filter]');
    if (!button) return;
    const preferred = selectedFilters();
    activeFilterTypes = activeFilterTypes.filter((type) => type !== button.dataset.removeFilter);
    renderAdditionalFilterRows(preferred);
  });
  $('reportSearch').addEventListener('input', () => { tablePage = 1; renderTable(); });
  $('reportPagePrevious')?.addEventListener('click', () => { tablePage = Math.max(1, tablePage - 1); renderTable(); });
  $('reportPageNext')?.addEventListener('click', () => { tablePage += 1; renderTable(); });
  $('reportPageSize')?.addEventListener('change', (event) => { tablePageSize = Math.max(1, Number(event.currentTarget.value) || 100); tablePage = 1; renderTable(); });
  $('reportHeader').addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-column-filter]');
    if (!trigger) return;
    event.stopPropagation();
    const column = tableColumns().find((item) => item.id === trigger.dataset.columnFilter);
    if (column) openColumnFilterMenu(column, trigger);
  });
  document.addEventListener('click', () => closeColumnFilterMenu());
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeColumnFilterMenu(); });
  window.addEventListener('resize', closeColumnFilterMenu);
  window.addEventListener('scroll', positionColumnFilterMenu, true);
  $('exportReport').addEventListener('click', exportCsv);
  $('reportRows').addEventListener('click', (event) => {
    const button = event.target.closest('.report-detail-button');
    if (!button?.dataset.cnes) return;
    if (button.dataset.action === 'services' && button.dataset.aih) runReport('services', button.dataset.cnes, true, button.dataset.aih, [Number(button.dataset.month) || activeMonth]);
    else runReport('detail', button.dataset.cnes, true, '', reportMonths);
  });
  $('backToSummary').addEventListener('click', () => {
    if (activeView === 'services') {
      const cachedDetail = cachedResult('detail', activeCnes, '', reportMonths);
      if (cachedDetail) {
        activeMonths = [...reportMonths]; activeMonth = activeMonths.at(-1) || activeMonth; routeUrl('detail', activeCnes, '', activeMonths); activeView = 'detail'; activeAih = ''; activeResult = cachedDetail; allRows = cachedDetail.rows || []; $('reportSearch').value = ''; resetTableViewState(); restoreTableDefaults(); renderTable();
      } else runReport('detail', activeCnes, true, '', reportMonths);
      return;
    }
    const cached = cachedResult('summary', '', '', reportMonths);
    if (cached) {
      activeMonths = [...reportMonths]; activeMonth = activeMonths.at(-1) || activeMonth; routeUrl('summary', '', '', activeMonths); activeView = 'summary'; activeCnes = ''; activeAih = ''; activeResult = cached; allRows = cached.rows || []; $('reportSearch').value = ''; resetTableViewState(); restoreTableDefaults(); renderTable();
    } else runReport('summary', '', true, '', reportMonths);
  });
  window.addEventListener('popstate', async () => {
    const current = new URLSearchParams(location.search);
    const year = Number(current.get('ano'));
    const months = [...new Set(current.getAll('mes').map(Number).filter((month) => month >= 1 && month <= 12))].sort((a, b) => a - b);
    const cnes = (current.get('cnes') || '').replace(/\D/g, '').slice(0, 7);
    const aih = (current.get('aih') || '').replace(/\D/g, '').slice(0, 13);
    const requestedId = current.get('relatorio') === 'sia-pa-belem' ? 'sia-pa-producao' : (current.get('relatorio') || 'sia-pa-producao');
    activateReport(reportConfigurations[requestedId] ? requestedId : 'sia-pa-producao');
    await loadReportDefaults(activeReport.id);
    const wantsReport = Object.prototype.hasOwnProperty.call(reportConfigurations, requestedId) || current.get('relatorio') === 'sia-pa-belem' || Boolean(year && months.length) || Boolean(cnes) || Boolean(aih);
    if (!wantsReport) { returnToCatalog(false); return; }
    const uf = String(current.get('uf') || 'PA').toUpperCase();
    const hasExplicitScope = current.has('uf') || current.has('municipio') || Object.values(filterDefinitions).some((definition) => current.has(definition.queryKey));
    const preferred = !year && !months.length && !hasExplicitScope ? applySetupPreference(uf) : filtersFromParams(current);
    if (hasExplicitScope || year || months.length) setUfOptions(uf);
    if (!year || !months.length) {
      setPageView('catalog', false);
      await openReportSetup(preferred);
      return;
    }
    setPageView('report', false);
    if (yearSelect.value !== String(year)) yearSelect.value = String(year);
    await prepareReportControls(preferred);
    updateScopeDescription();
    yearSelect.value = String(year);
    const availableMonths = [...monthSelect.options].map((option) => Number(option.value)).filter((month) => month >= 1 && month <= 12);
    setMonthOptions([...new Set([...availableMonths, ...months])], months);
    reportMonths = [...months];
    await runReport(aih ? 'services' : cnes ? 'detail' : 'summary', cnes, false, aih, months);
  });

  async function init() {
    activateReport(activeReport.id);
    if (linkedReport || linkedYear || linkedCnes) await loadReportDefaults(activeReport.id);
    const hasExplicitScope = params.has('uf') || params.has('municipio') || Object.values(filterDefinitions).some((definition) => params.has(definition.queryKey));
    const initialPreferred = linkedReport && !linkedYear && !linkedMonths.length && !hasExplicitScope ? applySetupPreference(linkedUf) : linkedFilters;
    if (hasExplicitScope || linkedYear || linkedMonths.length || !linkedReport) setUfOptions(linkedUf);
    setYears();
    updateScopeDescription();
    if (!linkedReport && !(linkedYear && linkedMonths.length) && !linkedCnes) return;
    if (linkedYear && linkedMonths.length) {
      setPageView('report', false);
      empty.hidden = true;
      showNotice('');
      setLoader(true, 'Preparando o relatório', 'Consultando as competências e conferindo os dados desta consulta.', null, true);
      try {
        await prepareReportControls(linkedFilters);
        updateScopeDescription();
        activeYear = linkedYear;
        const availableMonths = [...monthSelect.options].map((option) => Number(option.value)).filter((month) => month >= 1 && month <= 12);
        setMonthOptions([...new Set([...availableMonths, ...linkedMonths])], linkedMonths);
        reportMonths = [...linkedMonths];
        await runReport(linkedAih ? 'services' : linkedCnes ? 'detail' : 'summary', linkedCnes, false, linkedAih, linkedMonths);
      } catch (error) {
        showReportFailure(error);
      }
    } else await openReportSetup(initialPreferred);
  }

  init().catch((error) => {
    setLoader(false);
    if (linkedYear && linkedMonths.length) showReportFailure(error);
    setAvailability(error.message || 'Não foi possível iniciar as tabulações prontas.', 'error');
  });
})();
