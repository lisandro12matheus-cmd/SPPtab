(() => {
  'use strict';

  const FORM_URL = 'http://tabulasus.page.gd';
  const STORAGE_KEY = 'tabulasus-rating-v1';
  const MINUTE = 60 * 1000;
  const DAY = 24 * 60 * MINUTE;
  // Convite só depois de algum uso: tempo ativo acumulado no app e tempo na página atual.
  const MIN_TOTAL_USE = 10 * MINUTE;
  const MIN_PAGE_TIME = 2 * MINUTE;
  const DISMISS_WAIT = 7 * DAY;
  const SHOWN_WAIT = DAY;
  const TICK = 15 * 1000;

  function readState() {
    try {
      const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
      return value && typeof value === 'object' ? value : {};
    } catch (_) {
      return {};
    }
  }

  function writeState(patch) {
    try {
      const next = Object.assign(readState(), patch);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      return next;
    } catch (_) {
      return null;
    }
  }

  const svgNs = 'http://www.w3.org/2000/svg';
  function starIcon() {
    const svg = document.createElementNS(svgNs, 'svg');
    for (const [key, value] of Object.entries({ viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.7', 'stroke-linejoin': 'round', 'aria-hidden': 'true', focusable: 'false' })) svg.setAttribute(key, value);
    const path = document.createElementNS(svgNs, 'path');
    path.setAttribute('d', 'm12 3.6 2.5 5.1 5.6.8-4 4 1 5.5-5.1-2.7-5.1 2.7 1-5.5-4-4 5.6-.8z');
    svg.append(path);
    return svg;
  }

  function el(tag, attrs = {}, children = []) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (key === 'text') node.textContent = value;
      else node.setAttribute(key, value);
    }
    node.append(...children);
    return node;
  }

  // O formulário abre numa nova aba do navegador; ao abrir, o convite não volta mais.
  function linkToForm(attrs, children) {
    const link = el('a', Object.assign({ href: FORM_URL, target: '_blank', rel: 'noopener noreferrer' }, attrs), children);
    link.addEventListener('click', () => {
      writeState({ opened: true, openedAt: Date.now() });
      hideToast();
    });
    return link;
  }

  /* ---------- Item da sidebar ---------- */
  const sidebar = document.getElementById('spptabSidebar');
  if (sidebar && !sidebar.querySelector('.sidebar-rate')) {
    const label = 'Avalie o TabulaSUS';
    const button = linkToForm({ class: 'sidebar-rate', title: `${label} (abre em nova aba)` }, [
      el('span', { class: 'sidebar-rate-icon' }, [starIcon()]),
      el('span', { class: 'sidebar-rate-label', text: label })
    ]);
    const foot = sidebar.querySelector('.sidebar-foot');
    if (foot) sidebar.insertBefore(button, foot);
    else sidebar.append(button);
  }

  /* ---------- Convite ocasional ---------- */
  let toast = null;
  let timer = null;
  const pageStart = Date.now();
  let lastTick = Date.now();

  function hideToast() {
    if (!toast) return;
    toast.classList.remove('is-visible');
    const node = toast;
    toast = null;
    window.setTimeout(() => node.remove(), 260);
  }

  function isVisible(node) {
    if (!node || node.hidden) return false;
    const style = window.getComputedStyle(node);
    if (style.display === 'none' || style.visibility === 'hidden') return false;
    return node.getClientRects().length > 0;
  }

  function isBusy() {
    if (document.hidden) return true;
    if (document.querySelector('dialog[open]')) return true;
    if (document.querySelector('[aria-modal="true"]:not([hidden])')) return true;
    if (isVisible(document.getElementById('reportLoader'))) return true;
    if (isVisible(document.getElementById('launchSplash'))) return true;
    for (const node of document.querySelectorAll('[aria-busy="true"]')) {
      if (isVisible(node)) return true;
    }
    return document.querySelector('.app-shell.sidebar-mobile-expanded') !== null;
  }

  function eligible(state, now) {
    if (state.opened) return false;
    if (state.dismissedAt && now - state.dismissedAt < DISMISS_WAIT) return false;
    if (state.shownAt && now - state.shownAt < SHOWN_WAIT) return false;
    if ((state.usedMs || 0) < MIN_TOTAL_USE) return false;
    return now - pageStart >= MIN_PAGE_TIME;
  }

  function showToast() {
    writeState({ shownAt: Date.now() });
    const later = el('button', { class: 'rate-toast-later', type: 'button', text: 'Agora não' });
    const now = linkToForm({ class: 'rate-toast-now', text: 'Avaliar agora' });
    toast = el('aside', { class: 'rate-toast', role: 'status', 'aria-live': 'polite', 'aria-label': 'Convite para avaliar o TabulaSUS' }, [
      el('span', { class: 'rate-toast-mark' }, [starIcon()]),
      el('div', { class: 'rate-toast-copy' }, [
        el('strong', { text: 'Está gostando do TabulaSUS?' }),
        el('p', { text: 'Leva menos de um minuto e ajuda a melhorar a plataforma.' }),
        el('div', { class: 'rate-toast-actions' }, [later, now])
      ])
    ]);
    later.addEventListener('click', () => {
      writeState({ dismissedAt: Date.now() });
      hideToast();
    });
    document.body.append(toast);
    void toast.offsetWidth; // força o layout para a transição de entrada
    toast.classList.add('is-visible');
  }

  function tick() {
    const now = Date.now();
    const elapsed = Math.min(now - lastTick, TICK * 2);
    lastTick = now;
    if (document.hidden || toast) return;
    const state = writeState({ usedMs: (readState().usedMs || 0) + elapsed });
    if (!state) {
      // Sem localStorage não há como evitar repetição: não exibe o convite.
      window.clearInterval(timer);
      return;
    }
    if (!eligible(state, now) || isBusy()) return;
    window.clearInterval(timer);
    showToast();
  }

  if (!readState().opened) {
    timer = window.setInterval(tick, TICK);
    document.addEventListener('visibilitychange', () => { lastTick = Date.now(); });
  }
})();
