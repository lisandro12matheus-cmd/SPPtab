(() => {
  'use strict';

  const shell = document.querySelector('.app-shell');
  const sidebar = document.getElementById('spptabSidebar');
  const toggle = sidebar?.querySelector('.sidebar-toggle');
  if (!shell || !sidebar || !toggle) return;

  const storageKey = 'spptab-sidebar-collapsed-v1';
  const mobileQuery = window.matchMedia('(max-width: 760px)');
  const backdrop = document.createElement('button');
  backdrop.className = 'sidebar-backdrop';
  backdrop.type = 'button';
  backdrop.setAttribute('aria-label', 'Fechar menu');
  backdrop.hidden = true;
  shell.append(backdrop);

  let mobileExpanded = false;
  const navLinks = sidebar.querySelectorAll('nav .nav-item');
  const iconShapes = {
    home: [['path', { d:'m3 10 9-7 9 7v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z' }], ['path', { d:'M9 21v-7h6v7' }]],
    ready: [['rect', { x:'4', y:'3', width:'16', height:'18', rx:'2' }], ['path', { d:'M8 8h8M8 12h8M8 16h5' }]],
    files: [['circle', { cx:'10.5', cy:'10.5', r:'6.5' }], ['path', { d:'m16 16 5 5' }]],
    bases: [['ellipse', { cx:'12', cy:'5', rx:'8', ry:'3' }], ['path', { d:'M4 5v7c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12v7c0 1.7 3.6 3 8 3s8-1.3 8-3v-7' }]],
    tabular: [['rect', { x:'3', y:'4', width:'18', height:'16', rx:'2' }], ['path', { d:'M3 9h18M9 9v11M15 9v11M3 14h18' }]],
    sigtap: [['path', { d:'M12 6c-2.3-1.6-5-2-9-1.5v15c4-.5 6.7-.1 9 1.5 2.3-1.6 5-2 9-1.5v-15C17 4 14.3 4.4 12 6zM12 6v15' }], ['path', { d:'M16.5 9v5M14 11.5h5' }]],
    saved: [['path', { d:'M6 3h12a1 1 0 0 1 1 1v17l-7-4-7 4V4a1 1 0 0 1 1-1z' }], ['path', { d:'M9 8h6M9 11h6' }]]
  };

  function drawIcon(holder, shapes) {
    const namespace = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(namespace, 'svg');
    for (const [key, value] of Object.entries({ viewBox:'0 0 24 24', fill:'none', stroke:'currentColor', 'stroke-width':'1.8', 'stroke-linecap':'round', 'stroke-linejoin':'round', 'aria-hidden':'true', focusable:'false' })) svg.setAttribute(key, value);
    for (const [tag, attributes] of shapes) {
      const shape = document.createElementNS(namespace, tag);
      for (const [key, value] of Object.entries(attributes)) shape.setAttribute(key, value);
      svg.append(shape);
    }
    holder.replaceChildren(svg);
  }

  navLinks.forEach((link) => {
    const icon = link.querySelector('.nav-icon');
    if (icon && iconShapes[link.dataset.nav]) drawIcon(icon, iconShapes[link.dataset.nav]);
    const label = Array.from(link.childNodes)
      .filter((node) => node.nodeType === Node.TEXT_NODE)
      .map((node) => node.textContent)
      .join(' ')
      .replace(/\s+/g, ' ')
      .trim();
    if (label && !link.hasAttribute('title')) link.title = label;
  });

  function syncToggle() {
    const isExpanded = mobileQuery.matches
      ? mobileExpanded
      : !shell.classList.contains('sidebar-collapsed');
    const action = isExpanded ? 'Recolher menu' : 'Expandir menu';
    toggle.setAttribute('aria-expanded', String(isExpanded));
    toggle.setAttribute('aria-label', action);
    toggle.title = action;
    backdrop.hidden = !mobileExpanded || !mobileQuery.matches;
  }

  function setMobileExpanded(expanded) {
    mobileExpanded = expanded;
    shell.classList.toggle('sidebar-mobile-expanded', expanded);
    syncToggle();
    if (!expanded) toggle.focus();
  }

  function collapseForPanel() {
    if (mobileQuery.matches) {
      if (mobileExpanded) setMobileExpanded(false);
      return;
    }
    shell.classList.add('sidebar-collapsed');
    try { localStorage.setItem(storageKey, '1'); } catch (_) {}
    syncToggle();
  }

  try {
    shell.classList.toggle('sidebar-collapsed', localStorage.getItem(storageKey) === '1');
  } catch (_) {
    shell.classList.remove('sidebar-collapsed');
  }
  syncToggle();

  toggle.addEventListener('click', () => {
    if (mobileQuery.matches) {
      setMobileExpanded(!mobileExpanded);
      return;
    }

    const collapsed = shell.classList.toggle('sidebar-collapsed');
    try { localStorage.setItem(storageKey, collapsed ? '1' : '0'); } catch (_) {}
    syncToggle();
  });

  backdrop.addEventListener('click', () => setMobileExpanded(false));
  sidebar.querySelector('nav')?.addEventListener('click', (event) => {
    const link = event.target.closest('a.nav-item');
    if (link && !event.defaultPrevented && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) collapseForPanel();
  });
  document.addEventListener('tabulasus:panel-open', collapseForPanel);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && mobileExpanded) setMobileExpanded(false);
  });

  const onViewportChange = () => {
    if (!mobileQuery.matches && mobileExpanded) {
      mobileExpanded = false;
      shell.classList.remove('sidebar-mobile-expanded');
    }
    syncToggle();
  };
  if (mobileQuery.addEventListener) mobileQuery.addEventListener('change', onViewportChange);
  else mobileQuery.addListener(onViewportChange);

  window.addEventListener('storage', (event) => {
    if (event.key !== storageKey || mobileQuery.matches) return;
    shell.classList.toggle('sidebar-collapsed', event.newValue === '1');
    syncToggle();
  });
})();
