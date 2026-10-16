(() => {
  const link = document.getElementById('savedTabulationsNav');
  if (!link) return;
  const key = 'spptab-active-file-v1';
  const refresh = () => {
    try { link.hidden = !localStorage.getItem(key); }
    catch (_) { link.hidden = true; }
  };
  refresh();
  window.addEventListener('storage', refresh);
  window.addEventListener('spptab-active-file-change', refresh);
  document.addEventListener('visibilitychange', refresh);
})();
