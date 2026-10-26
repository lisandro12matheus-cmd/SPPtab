(() => {
  'use strict';
  const labels = { group:'Grupo', subgroup:'Subgrupo', form:'Forma de organização', complexity:'Complexidade', financing:'Financiamento', modality:'Modalidade', registration:'Instrumento de registro', cbo:'CBO', cid:'CID', service_class:'Serviço / classificação', habilitation:'Habilitação', sex:'Sexo' };
  const staticOptions = { complexity:[['0','Não se aplica'],['1','Atenção básica'],['2','Média complexidade'],['3','Alta complexidade']], sex:[['I','Indiferente'],['M','Masculino'],['F','Feminino'],['N','Não se aplica']] };
  window.SPPtabSigtapWidget = function mount(root, api, getCompetence) {
    const selected = {};
    const title = document.createElement('div'); title.className = 'section-label';
    const heading = document.createElement('div'); heading.append(Object.assign(document.createElement('h3'), { textContent:'Cruzamento SIGTAP' }), Object.assign(document.createElement('p'), { textContent:'Filtre a produção por atributos dos procedimentos publicados na mesma competência. Os códigos são cruzados antes dos totais.' })); title.append(heading);
    const controls = document.createElement('div'); controls.className = 'sigtap-widget-controls';
    const kind = document.createElement('select'); kind.setAttribute('aria-label','Atributo SIGTAP'); kind.add(new Option('Escolha um atributo…','')); Object.entries(labels).forEach(([key,label]) => kind.add(new Option(label,key)));
    const query = document.createElement('input'); query.type = 'search'; query.placeholder = 'Pesquisar código ou descrição'; query.setAttribute('aria-label','Pesquisar opção SIGTAP'); query.hidden = true;
    const value = document.createElement('select'); value.setAttribute('aria-label','Valor do atributo SIGTAP'); value.add(new Option('Escolha um valor…',''));
    const add = document.createElement('button'); add.type = 'button'; add.className = 'button button-secondary'; add.textContent = 'Adicionar filtro'; add.disabled = true;
    controls.append(kind,query,value,add);
    const chips = document.createElement('div'); chips.className = 'sigtap-widget-chips';
    const status = document.createElement('small'); status.className = 'sigtap-widget-status'; status.setAttribute('role','status');
    root.replaceChildren(title,controls,chips,status);
    let requestId = 0;
    function render() {
      chips.replaceChildren();
      Object.entries(selected).forEach(([key,entry]) => { const button = document.createElement('button'); button.type = 'button'; button.textContent = `${labels[key]}: ${entry.label} ×`; button.addEventListener('click', () => { delete selected[key]; render(); root.dispatchEvent(new Event('change')); }); chips.append(button); });
      const competence = getCompetence();
      status.textContent = competence ? `SIGTAP da competência ${competence.slice(4,6)}/${competence.slice(0,4)}. ${Object.keys(selected).length ? 'Os atributos escolhidos serão combinados com os demais filtros.' : 'Sem filtro, a produção permanece completa.'}` : 'Escolha uma competência para aplicar o cruzamento.';
    }
    async function options() {
      const current = ++requestId, selectedKind = kind.value;
      value.replaceChildren(new Option('Escolha um valor…','')); add.disabled = true;
      query.hidden = !selectedKind || Boolean(staticOptions[selectedKind]);
      if (!selectedKind) return;
      if (staticOptions[selectedKind]) { staticOptions[selectedKind].forEach(([code,label]) => value.add(new Option(`${code} · ${label}`,code))); return; }
      const competence = getCompetence(); if (!competence) { status.textContent = 'Escolha a competência antes de buscar as opções.'; return; }
      status.textContent = 'Consultando opções oficiais do SIGTAP…';
      try {
        const response = await api({ action:'sigtap_options', competence, kind:selectedKind, query:query.value.trim() });
        if (current !== requestId) return;
        (response.options || []).forEach(item => value.add(new Option(`${item.code} · ${item.label}`,item.code)));
        status.textContent = response.truncated ? 'Mostrando 200 opções. Digite o código ou parte do nome para localizar mais.' : `${response.totalOptions || 0} opção(ões) nesta competência.`;
      } catch (error) { if (current === requestId) status.textContent = error.message || 'Não foi possível consultar o SIGTAP.'; }
    }
    kind.addEventListener('change', () => { query.value = ''; options(); });
    let timer; query.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(options,250); });
    value.addEventListener('change', () => { add.disabled = !value.value; });
    add.addEventListener('click', () => { if (!kind.value || !value.value) return; selected[kind.value] = { value:value.value, label:value.selectedOptions[0].textContent }; render(); root.dispatchEvent(new Event('change')); });
    render();
    return {
      getFilters: () => Object.fromEntries(Object.entries(selected).map(([key,entry]) => [key,entry.value])),
      setFilters: (filters) => { Object.keys(selected).forEach(key => delete selected[key]); if (filters && typeof filters === 'object') Object.entries(filters).forEach(([key,val]) => { if (labels[key] && typeof val === 'string') selected[key] = {value:val,label:val}; }); render(); },
      refresh: () => { query.value = ''; options(); render(); },
      setEnabled: (enabled) => { root.hidden = !enabled; if (!enabled) Object.keys(selected).forEach(key => delete selected[key]); render(); }
    };
  };
})();
