(() => {
  'use strict';
  const key = 'gestati.tema';
  const root = document.documentElement;
  const valid = value => ['claro', 'escuro'].includes(value);
  function apply(value) {
    root.dataset.theme = valid(value) ? value : 'claro';
    document.querySelectorAll('[name="tema"]').forEach(input => {
      input.checked = input.value === root.dataset.theme;
    });
  }
  try { apply(localStorage.getItem(key)); }
  catch { apply('claro'); }
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[name="tema"]').forEach(input => {
      input.checked = input.value === root.dataset.theme;
      input.addEventListener('change', () => {
        if (!input.checked || !valid(input.value)) return;
        apply(input.value);
        let text = `Tema ${input.value} aplicado.`;
        try { localStorage.setItem(key, input.value); }
        catch { text += ' Não foi possível salvar a preferência neste navegador.'; }
        const status = document.getElementById('theme-status');
        if (status) status.textContent = text;
      });
    });
  });
  window.addEventListener('storage', event => {
    if (event.key === key || event.key === null) apply(event.newValue);
  });
})();
