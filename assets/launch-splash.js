(() => {
  'use strict';

  const splash = document.getElementById('launchSplash');
  if (!splash) return;
  if (document.documentElement.classList.contains('skip-launch-splash')) {
    splash.remove();
    return;
  }
  try { sessionStorage.setItem('spptab-launch-shown', '1'); } catch (_) {}

  const message = document.getElementById('launchMessage');
  const messages = ['Carregando recursos', 'Ajustando caminhos', 'Preparando seus dados', 'Quase pronto'];
  let messageIndex = 0;
  let messageSwap = 0;
  const messageCycle = window.setInterval(() => {
    if (!message) return;
    message.classList.add('is-changing');
    messageSwap = window.setTimeout(() => {
      messageIndex = (messageIndex + 1) % messages.length;
      message.textContent = messages[messageIndex];
      message.classList.remove('is-changing');
    }, 180);
  }, 1250);

  const startedAt = performance.now();
  const minimumTime = 5000;

  const dismiss = () => {
    const remaining = Math.max(0, minimumTime - (performance.now() - startedAt));
    window.setTimeout(() => {
      window.clearInterval(messageCycle);
      window.clearTimeout(messageSwap);
      splash.classList.add('is-hidden');
      window.setTimeout(() => splash.remove(), 380);
    }, remaining);
  };

  if (document.readyState === 'complete') dismiss();
  else window.addEventListener('load', dismiss, { once: true });
})();
