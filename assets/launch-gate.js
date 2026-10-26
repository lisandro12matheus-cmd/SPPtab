(() => {
  'use strict';
  const fileEntry = new URLSearchParams(window.location.search).get('etapa') === 'arquivos';
  let alreadyShown = false;
  try {
    alreadyShown = sessionStorage.getItem('spptab-launch-shown') === '1';
    if (fileEntry) sessionStorage.setItem('spptab-launch-shown', '1');
  } catch (_) {}
  if (fileEntry || alreadyShown) document.documentElement.classList.add('skip-launch-splash');
})();
