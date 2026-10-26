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

  navLinks.forEach((link) => {
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
    if (mobileQuery.matches && event.target.closest('a')) setMobileExpanded(false);
  });
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
